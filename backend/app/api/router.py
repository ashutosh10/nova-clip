import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, status
from redis.exceptions import RedisError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.redis import get_async_redis
from app.models.entities import Clip, ClipStatus, Job, JobKind, JobStatus, Project, ProjectStatus
from app.schemas.api import (
    ClipGenerateRequest, ClipRead, ClipTrimRequest, GenerateResponse, GenerateVideoResponse, JobRead, ProjectCreate,
    ProjectRead, ProjectUpdate, ReorderRequest, StitchRequest, VideoGenerateRequest,
)
from app.services.ffmpeg import MediaProcessingError, create_thumbnail, duration
from app.services.progress import job_channel
from app.workers.tasks import generate_clip, generate_sequence, stitch_project

router = APIRouter()


def media_url(path: str | None) -> str | None:
    if not path:
        return None
    try:
        relative = Path(path).resolve().relative_to(settings.media_root.resolve())
    except ValueError:
        return None
    return f"{settings.public_media_url.rstrip('/')}/{relative.as_posix()}"


def clip_read(clip: Clip) -> ClipRead:
    return ClipRead.model_validate(clip).model_copy(update={"media_url": media_url(clip.file_path), "thumbnail_url": media_url(clip.thumbnail_path)})


def project_read(project: Project) -> ProjectRead:
    return ProjectRead.model_validate(project).model_copy(
        update={"clips": [clip_read(c) for c in project.clips], "master_url": media_url(project.master_path)}
    )


def job_read(job: Job) -> JobRead:
    return JobRead.model_validate(job).model_copy(update={"result_url": media_url(job.result_path)})


async def require_project(project_id: str, db: AsyncSession) -> Project:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate, db: AsyncSession = Depends(get_db)) -> ProjectRead:
    project = Project(**payload.model_dump())
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project_read(project)


@router.get("/projects", response_model=list[ProjectRead])
async def list_projects(db: AsyncSession = Depends(get_db)) -> list[ProjectRead]:
    result = await db.execute(select(Project).order_by(Project.updated_at.desc()))
    return [project_read(item) for item in result.scalars().unique().all()]


@router.get("/projects/{project_id}", response_model=ProjectRead)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)) -> ProjectRead:
    return project_read(await require_project(project_id, db))

@router.patch("/projects/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: str, payload: ProjectUpdate, db: AsyncSession = Depends(get_db)
) -> ProjectRead:
    project = await require_project(project_id, db)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("description") == "":
        changes["description"] = None
    for field, value in changes.items():
        setattr(project, field, value)
    await db.commit()
    await db.refresh(project)
    return project_read(project)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)) -> None:
    project = await require_project(project_id, db)
    active_job = await db.scalar(
        select(Job.id)
        .where(
            Job.project_id == project_id,
            Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
        )
        .limit(1)
    )
    if active_job:
        raise HTTPException(status_code=409, detail="Wait for the active project job to finish before deleting")

    projects_root = (settings.media_root / "projects").resolve()
    project_dir = (projects_root / project.id).resolve()
    if project_dir.parent != projects_root:
        raise HTTPException(status_code=500, detail="Invalid project media path")
    try:
        if project_dir.exists():
            shutil.rmtree(project_dir)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Could not remove project media") from exc
    await db.delete(project)
    await db.commit()


async def shift_positions(db: AsyncSession, project_id: str, from_position: int) -> None:
    clips = (await db.execute(select(Clip).where(Clip.project_id == project_id, Clip.position >= from_position))).scalars().all()
    # Use a disjoint negative range so PostgreSQL can check the unique
    # constraint row-by-row without transient position collisions.
    for clip in clips:
        clip.position = -(clip.position + 1)
    await db.flush()
    for clip in clips:
        clip.position = -clip.position
    await db.flush()


@router.post("/projects/{project_id}/generate-clip", response_model=GenerateResponse, status_code=status.HTTP_202_ACCEPTED)
async def enqueue_generation(project_id: str, payload: ClipGenerateRequest, db: AsyncSession = Depends(get_db)) -> GenerateResponse:
    project = await require_project(project_id, db)
    position = payload.position if payload.position is not None else len(project.clips)
    if position > len(project.clips):
        raise HTTPException(status_code=422, detail="position cannot exceed the current clip count")
    await shift_positions(db, project_id, position)
    clip = Clip(project_id=project_id, position=position, prompt=payload.prompt, status=ClipStatus.QUEUED)
    db.add(clip)
    await db.flush()
    job = Job(project_id=project_id, clip_id=clip.id, kind=JobKind.GENERATE, status=JobStatus.QUEUED, message="Queued for GPU")
    db.add(job)
    project.status = ProjectStatus.DRAFT
    await db.commit()
    try:
        task = generate_clip.apply_async(kwargs={"job_id": job.id, "options": payload.model_dump(exclude={"prompt", "position"})}, queue="gpu")
        job.celery_task_id = task.id
        await db.commit()
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.error = f"Could not enqueue generation: {exc}"
        clip.status = ClipStatus.FAILED
        await db.commit()
        raise HTTPException(status_code=503, detail="Generation queue is unavailable") from exc
    await db.refresh(clip)
    await db.refresh(job)
    return GenerateResponse(clip=clip_read(clip), job=job_read(job))


@router.post("/projects/{project_id}/generate-video", response_model=GenerateVideoResponse, status_code=status.HTTP_202_ACCEPTED)
async def enqueue_video(project_id: str, payload: VideoGenerateRequest, db: AsyncSession = Depends(get_db)) -> GenerateVideoResponse:
    project = await require_project(project_id, db)
    shot_count = payload.duration_seconds // 5
    start_position = len(project.clips)
    clips = [
        Clip(
            project_id=project_id,
            position=start_position + index,
            prompt=payload.prompt,
            status=ClipStatus.QUEUED,
        )
        for index in range(shot_count)
    ]
    db.add_all(clips)
    await db.flush()
    job = Job(
        project_id=project_id,
        kind=JobKind.GENERATE,
        status=JobStatus.QUEUED,
        message=f"Queued for GPU  -  {shot_count} shots",
    )
    db.add(job)
    project.status = ProjectStatus.PROCESSING
    project.master_path = None
    await db.commit()
    try:
        options = payload.model_dump(exclude={"prompt", "duration_seconds"})
        options["shot_duration_seconds"] = 5.0
        task = generate_sequence.apply_async(
            kwargs={
                "job_id": job.id,
                "clip_ids": [clip.id for clip in clips],
                "prompt": payload.prompt,
                "options": options,
            },
            queue="gpu",
        )
        job.celery_task_id = task.id
        await db.commit()
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.error = f"Could not enqueue video generation: {exc}"
        project.status = ProjectStatus.FAILED
        for clip in clips:
            clip.status = ClipStatus.FAILED
            clip.error = "Generation queue is unavailable"
        await db.commit()
        raise HTTPException(status_code=503, detail="Generation queue is unavailable") from exc

    for clip in clips:
        await db.refresh(clip)
    await db.refresh(job)
    return GenerateVideoResponse(clips=[clip_read(clip) for clip in clips], job=job_read(job))



@router.post("/projects/{project_id}/clips/upload", response_model=ClipRead, status_code=status.HTTP_201_CREATED)
async def upload_clip(
    project_id: str, file: UploadFile = File(...), position: int | None = None, db: AsyncSession = Depends(get_db)
) -> ClipRead:
    project = await require_project(project_id, db)
    allowed = {"video/mp4", "video/quicktime", "video/webm", "video/x-matroska"}
    if file.content_type not in allowed:
        raise HTTPException(status_code=415, detail="Upload MP4, MOV, WebM, or MKV video")
    target_position = len(project.clips) if position is None else position
    if target_position < 0 or target_position > len(project.clips):
        raise HTTPException(status_code=422, detail="Invalid sequence position")
    await shift_positions(db, project_id, target_position)
    clip = Clip(project_id=project_id, position=target_position, status=ClipStatus.QUEUED)
    db.add(clip)
    await db.flush()
    suffix = Path(file.filename or "upload.mp4").suffix.lower() or ".mp4"
    target_dir = settings.media_root / "projects" / project_id / "clips" / clip.id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"source{suffix}"
    try:
        with target.open("wb") as destination:
            shutil.copyfileobj(file.file, destination)
        if target.stat().st_size > 2 * 1024**3:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=413, detail="Uploads are limited to 2 GB")
        clip.duration_seconds = duration(target)
        clip.file_path = str(target)
        thumbnail = target_dir / "thumbnail.jpg"
        create_thumbnail(target, thumbnail)
        clip.thumbnail_path = str(thumbnail)
        clip.status = ClipStatus.READY
        await db.commit()
        await db.refresh(clip)
        return clip_read(clip)
    except HTTPException:
        raise
    except MediaProcessingError as exc:
        target.unlink(missing_ok=True)
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()


@router.patch("/projects/{project_id}/clips/{clip_id}/trim", response_model=ClipRead)
async def trim_clip(project_id: str, clip_id: str, payload: ClipTrimRequest, db: AsyncSession = Depends(get_db)) -> ClipRead:
    clip = await db.get(Clip, clip_id)
    if not clip or clip.project_id != project_id:
        raise HTTPException(status_code=404, detail="Clip not found")
    if payload.trim_end is not None and clip.duration_seconds and payload.trim_end > clip.duration_seconds:
        raise HTTPException(status_code=422, detail="trim_end exceeds clip duration")
    clip.trim_start = payload.trim_start
    clip.trim_end = payload.trim_end
    await db.commit()
    await db.refresh(clip)
    return clip_read(clip)


@router.delete("/projects/{project_id}/clips/{clip_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_clip(project_id: str, clip_id: str, db: AsyncSession = Depends(get_db)) -> None:
    clip = await db.get(Clip, clip_id)
    if not clip or clip.project_id != project_id:
        raise HTTPException(status_code=404, detail="Clip not found")
    removed_position = clip.position
    await db.delete(clip)
    await db.flush()
    remaining = (await db.execute(select(Clip).where(Clip.project_id == project_id, Clip.position > removed_position))).scalars().all()
    for item in remaining:
        item.position = -(item.position + 1)
    await db.flush()
    for item in remaining:
        item.position = -item.position - 2
    await db.commit()


@router.post("/projects/{project_id}/reorder", response_model=ProjectRead)
async def reorder_clips(project_id: str, payload: ReorderRequest, db: AsyncSession = Depends(get_db)) -> ProjectRead:
    project = await require_project(project_id, db)
    existing = {clip.id for clip in project.clips}
    if set(payload.clip_ids) != existing or len(payload.clip_ids) != len(existing):
        raise HTTPException(status_code=422, detail="clip_ids must contain every project clip exactly once")
    # Two-phase update avoids violating the unique (project, position) constraint.
    for index, clip_id in enumerate(payload.clip_ids):
        await db.execute(update(Clip).where(Clip.id == clip_id).values(position=-(index + 1)))
    await db.flush()
    for index, clip_id in enumerate(payload.clip_ids):
        await db.execute(update(Clip).where(Clip.id == clip_id).values(position=index))
    await db.commit()
    await db.refresh(project)
    return project_read(project)


@router.post("/projects/{project_id}/stitch", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
async def enqueue_stitch(project_id: str, payload: StitchRequest, db: AsyncSession = Depends(get_db)) -> JobRead:
    project = await require_project(project_id, db)
    if not project.clips:
        raise HTTPException(status_code=422, detail="Add at least one clip before exporting")
    if any(clip.status != ClipStatus.READY or not clip.file_path for clip in project.clips):
        raise HTTPException(status_code=409, detail="All clips must be ready before exporting")
    job = Job(project_id=project_id, kind=JobKind.STITCH, status=JobStatus.QUEUED, message="Export queued")
    db.add(job)
    project.status = ProjectStatus.PROCESSING
    await db.commit()
    try:
        task = stitch_project.apply_async(kwargs={"job_id": job.id, "options": payload.model_dump()}, queue="media")
        job.celery_task_id = task.id
        await db.commit()
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.error = f"Could not enqueue export: {exc}"
        project.status = ProjectStatus.FAILED
        await db.commit()
        raise HTTPException(status_code=503, detail="Media queue is unavailable") from exc
    await db.refresh(job)
    return job_read(job)


@router.get("/jobs/{job_id}", response_model=JobRead)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)) -> JobRead:
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_read(job)


@router.websocket("/jobs/{job_id}/stream")
async def job_stream(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    redis = get_async_redis()
    pubsub = redis.pubsub()
    try:
        latest = await redis.get(f"jobs:{job_id}:latest")
        if latest:
            await websocket.send_text(latest)
            parsed = json.loads(latest)
            if parsed.get("status") in {"SUCCEEDED", "FAILED"}:
                return
        await pubsub.subscribe(job_channel(job_id))
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=25)
            if message and message.get("data"):
                data = message["data"]
                await websocket.send_text(data)
                if json.loads(data).get("status") in {"SUCCEEDED", "FAILED"}:
                    return
            else:
                await websocket.send_json({"job_id": job_id, "type": "heartbeat"})
    except (WebSocketDisconnect, RedisError):
        return
    finally:
        await pubsub.unsubscribe(job_channel(job_id))
        await pubsub.close()
        await redis.close()

