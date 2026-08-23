import asyncio
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path

from celery import Task
from redis.exceptions import LockError
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.redis import get_sync_redis
from app.models.entities import Clip, ClipStatus, Job, JobStatus, Project, ProjectStatus
from app.services.ffmpeg import ClipInput, create_thumbnail, duration, stitch_clips
from app.services.generator import generate_video
from app.services.llm import expand_prompt, plan_shots
from app.services.progress import publish_progress
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_async_runner = asyncio.Runner()

def _run(coroutine):
    return _async_runner.run(coroutine)


async def _update_job(job_id: str, **values) -> None:
    async with SessionLocal() as db:
        job = await db.get(Job, job_id)
        if job:
            for key, value in values.items():
                setattr(job, key, value)
            await db.commit()


def _progress(job_id: str, **payload) -> None:
    publish_progress(job_id, payload)


class FailureAwareTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        job_id = kwargs.get("job_id") or (args[0] if args else None)
        if job_id:
            try:
                _run(_mark_failed(job_id, f"{type(exc).__name__}: {exc}"))
            except Exception:
                logger.exception("Could not persist task failure")
        super().on_failure(exc, task_id, args, kwargs, einfo)


async def _mark_failed(job_id: str, error: str) -> None:
    async with SessionLocal() as db:
        job = await db.get(Job, job_id)
        if not job:
            return
        job.status = JobStatus.FAILED
        job.error = error[-4000:]
        job.message = "Failed"
        job.finished_at = datetime.now(timezone.utc)
        if job.clip_id:
            clip = await db.get(Clip, job.clip_id)
            if clip:
                clip.status = ClipStatus.FAILED
                clip.error = error[-4000:]
        project = await db.get(Project, job.project_id)
        if project and job.clip_id is None:
            project.status = ProjectStatus.FAILED
        await db.commit()
    publish_progress(job_id, {"status": "FAILED", "message": "Failed", "error": error[-4000:]})


@celery_app.task(bind=True, base=FailureAwareTask, name="app.workers.tasks.generate_clip")
def generate_clip(self, job_id: str, options: dict) -> dict:
    redis = get_sync_redis()
    lock = redis.lock("nova:gpu:generation", timeout=settings.gpu_lock_timeout_seconds, blocking_timeout=settings.gpu_lock_timeout_seconds)
    acquired = False
    try:
        acquired = lock.acquire(blocking=True)
        if not acquired:
            raise RuntimeError("Timed out waiting for the single-job GPU lock")
        return _run(_generate_clip(job_id, options))
    except Exception:
        logger.error("Generation task failed\n%s", traceback.format_exc())
        raise
    finally:
        if acquired:
            try:
                lock.release()
            except LockError:
                logger.warning("GPU lock expired before release")


async def _generate_clip(job_id: str, options: dict) -> dict:
    async with SessionLocal() as db:
        job = await db.get(Job, job_id)
        if not job or not job.clip_id:
            raise RuntimeError("Generation job or clip does not exist")
        clip = await db.get(Clip, job.clip_id)
        project = await db.get(Project, job.project_id)
        if not clip or not project:
            raise RuntimeError("Project or clip was deleted")
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        job.message = "Enhancing prompt"
        clip.status = ClipStatus.GENERATING
        await db.commit()
        clip_id, project_id = clip.id, project.id
        width, height, fps = project.width, project.height, project.fps
        original_prompt = clip.prompt or ""
    publish_progress(job_id, {"status": "RUNNING", "progress": 1, "message": "Enhancing prompt"})
    expanded = await expand_prompt(original_prompt)
    async with SessionLocal() as db:
        clip = await db.get(Clip, clip_id)
        if not clip:
            raise RuntimeError("Clip was deleted while queued")
        clip.expanded_prompt = expanded
        await db.commit()

    await _update_job(job_id, progress=3, message="Loading Wan 2.1 FP8 pipeline")
    _progress(job_id, status=JobStatus.RUNNING, progress=3, message="Loading Wan 2.1 FP8 pipeline")

    project_dir = settings.media_root / "projects" / project_id / "clips" / clip_id
    output = project_dir / "video.mp4"
    thumbnail = project_dir / "thumbnail.jpg"

    def on_progress(step: int, total: int, speed: float, eta: float) -> None:
        value = 5 + (step / total) * 85
        _progress(
            job_id, status=JobStatus.RUNNING, progress=value, current_step=step, total_steps=total,
            speed=speed, eta_seconds=eta, message=f"Sampling {step}/{total}",
        )

    generate_video(
        expanded, output, options["duration_seconds"], width, height, fps,
        options["inference_steps"], options["guidance_scale"], options.get("seed"), on_progress,
        options.get("generation_preset", "quality"),
    )
    _progress(job_id, status=JobStatus.RUNNING, progress=94, message="Creating thumbnail")
    create_thumbnail(output, thumbnail)
    actual_duration = duration(output)
    async with SessionLocal() as db:
        clip = await db.get(Clip, clip_id)
        job = await db.get(Job, job_id)
        if not clip or not job:
            raise RuntimeError("Job data was deleted during generation")
        clip.file_path = str(output)
        clip.thumbnail_path = str(thumbnail)
        clip.duration_seconds = actual_duration
        clip.status = ClipStatus.READY
        clip.error = None
        job.status = JobStatus.SUCCEEDED
        job.progress = 100
        job.message = "Clip ready"
        job.result_path = str(output)
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()
    payload = {"status": "SUCCEEDED", "progress": 100, "message": "Clip ready", "result_path": str(output)}
    publish_progress(job_id, payload)
    return payload


@celery_app.task(bind=True, base=FailureAwareTask, name="app.workers.tasks.generate_sequence")
def generate_sequence(self, job_id: str, clip_ids: list[str], prompt: str, options: dict) -> dict:
    redis = get_sync_redis()
    lock = redis.lock(
        "nova:gpu:generation",
        timeout=settings.gpu_lock_timeout_seconds,
        blocking_timeout=settings.gpu_lock_timeout_seconds,
    )
    acquired = False
    try:
        acquired = lock.acquire(blocking=True)
        if not acquired:
            raise RuntimeError("Timed out waiting for the single-job GPU lock")
        return _run(_generate_sequence(job_id, clip_ids, prompt, options))
    except Exception as exc:
        try:
            _run(_mark_sequence_failed(clip_ids, f"{type(exc).__name__}: {exc}"))
        except Exception:
            logger.exception("Could not mark sequence clips as failed")
        logger.error("Sequence generation task failed\n%s", traceback.format_exc())
        raise
    finally:
        if acquired:
            try:
                lock.release()
            except LockError:
                logger.warning("GPU lock expired before release")


async def _mark_sequence_failed(clip_ids: list[str], error: str) -> None:
    async with SessionLocal() as db:
        result = await db.execute(select(Clip).where(Clip.id.in_(clip_ids)))
        for clip in result.scalars().all():
            if clip.status != ClipStatus.READY:
                clip.status = ClipStatus.FAILED
                clip.error = error[-4000:]
        await db.commit()


async def _generate_sequence(job_id: str, clip_ids: list[str], prompt: str, options: dict) -> dict:
    shot_count = len(clip_ids)
    if not shot_count:
        raise RuntimeError("Sequence has no shots")

    async with SessionLocal() as db:
        job = await db.get(Job, job_id)
        if not job:
            raise RuntimeError("Sequence job does not exist")
        project = await db.get(Project, job.project_id)
        if not project:
            raise RuntimeError("Project was deleted")
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        job.progress = 1
        job.message = f"Planning {shot_count} shots"
        await db.commit()
        project_id, width, height, fps = project.id, project.width, project.height, project.fps

    publish_progress(
        job_id,
        {"status": "RUNNING", "progress": 1, "message": f"Planning {shot_count} shots"},
    )
    shot_prompts = await plan_shots(prompt, shot_count)
    outputs: list[Path] = []
    shot_duration = float(options.get("shot_duration_seconds", 5.0))

    for index, (clip_id, shot_prompt) in enumerate(zip(clip_ids, shot_prompts, strict=True)):
        async with SessionLocal() as db:
            clip = await db.get(Clip, clip_id)
            job = await db.get(Job, job_id)
            if not clip or not job:
                raise RuntimeError("Sequence data was deleted while queued")
            clip.status = ClipStatus.GENERATING
            clip.expanded_prompt = shot_prompt
            clip.error = None
            job.message = (
                f"Creating shot {index + 1} of {shot_count}"
                if index == 0 else f"Continuing from the previous 5 frames - shot {index + 1} of {shot_count}"
            )
            await db.commit()

        project_dir = settings.media_root / "projects" / project_id / "clips" / clip_id
        output = project_dir / "video.mp4"
        thumbnail = project_dir / "thumbnail.jpg"

        def on_progress(step: int, total: int, speed: float, eta: float, shot_index: int = index) -> None:
            shot_fraction = step / max(total, 1)
            value = 5 + ((shot_index + shot_fraction) / shot_count) * 82
            _progress(
                job_id,
                status=JobStatus.RUNNING,
                progress=value,
                current_step=step,
                total_steps=total,
                speed=speed,
                eta_seconds=eta,
                message=f"Shot {shot_index + 1}/{shot_count} - sampling {step}/{total}",
            )

        generate_video(
            shot_prompt,
            output,
            shot_duration,
            width,
            height,
            fps,
            options["inference_steps"],
            options["guidance_scale"],
            options.get("seed"),
            on_progress,
            options.get("generation_preset", "fast"),
            conditioning_video=outputs[-1] if outputs else None,
        )
        create_thumbnail(output, thumbnail)
        actual_duration = duration(output)
        outputs.append(output)
        async with SessionLocal() as db:
            clip = await db.get(Clip, clip_id)
            job = await db.get(Job, job_id)
            if not clip or not job:
                raise RuntimeError("Sequence data was deleted during generation")
            clip.file_path = str(output)
            clip.thumbnail_path = str(thumbnail)
            clip.duration_seconds = actual_duration
            clip.status = ClipStatus.READY
            clip.error = None
            job.progress = 5 + ((index + 1) / shot_count) * 82
            job.current_step = None
            job.total_steps = None
            await db.commit()

    await _update_job(job_id, progress=90, message="Combining shots")
    publish_progress(job_id, {"status": "RUNNING", "progress": 90, "message": "Combining shots"})

    output = settings.media_root / "projects" / project_id / "exports" / f"master-{job_id}.mp4"

    def on_stitch_progress(value: float, message: str) -> None:
        mapped = 90 + (value / 100) * 9
        _progress(job_id, status=JobStatus.RUNNING, progress=mapped, message="Combining shots")

    stitch_clips(
        [ClipInput(path, 0.0, None) for path in outputs],
        output,
        width,
        height,
        fps,
        "cut",
        0.5,
        "h264",
        on_stitch_progress,
    )

    async with SessionLocal() as db:
        job = await db.get(Job, job_id)
        project = await db.get(Project, project_id)
        if not job or not project:
            raise RuntimeError("Sequence data was deleted during export")
        job.status = JobStatus.SUCCEEDED
        job.progress = 100
        job.message = "Video ready"
        job.result_path = str(output)
        job.finished_at = datetime.now(timezone.utc)
        project.status = ProjectStatus.READY
        project.master_path = str(output)
        await db.commit()

    payload = {"status": "SUCCEEDED", "progress": 100, "message": "Video ready", "result_path": str(output)}
    publish_progress(job_id, payload)
    return payload



@celery_app.task(bind=True, base=FailureAwareTask, name="app.workers.tasks.stitch_project")
def stitch_project(self, job_id: str, options: dict) -> dict:
    return _run(_stitch_project(job_id, options))


async def _stitch_project(job_id: str, options: dict) -> dict:
    async with SessionLocal() as db:
        job = await db.get(Job, job_id)
        if not job:
            raise RuntimeError("Stitch job does not exist")
        result = await db.execute(select(Project).where(Project.id == job.project_id))
        project = result.scalar_one_or_none()
        if not project:
            raise RuntimeError("Project was deleted")
        ready = [clip for clip in project.clips if clip.status == ClipStatus.READY and clip.file_path]
        if len(ready) != len(project.clips):
            raise RuntimeError("Every project clip must be ready before stitching")
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        job.message = "Preparing clips"
        project.status = ProjectStatus.PROCESSING
        await db.commit()
        project_id, width, height, fps = project.id, project.width, project.height, project.fps
        inputs = [ClipInput(Path(c.file_path), c.trim_start, c.trim_end) for c in ready]

    output = settings.media_root / "projects" / project_id / "exports" / f"master-{job_id}.mp4"

    def on_progress(value: float, message: str) -> None:
        _progress(job_id, status=JobStatus.RUNNING, progress=value, message=message)

    stitch_clips(
        inputs, output, width, height, fps, options["transition"], options["transition_seconds"], options["codec"], on_progress
    )
    async with SessionLocal() as db:
        job = await db.get(Job, job_id)
        project = await db.get(Project, project_id)
        if not job or not project:
            raise RuntimeError("Project or job was deleted during export")
        job.status = JobStatus.SUCCEEDED
        job.progress = 100
        job.message = "Master export ready"
        job.result_path = str(output)
        job.finished_at = datetime.now(timezone.utc)
        project.status = ProjectStatus.READY
        project.master_path = str(output)
        await db.commit()
    payload = {"status": "SUCCEEDED", "progress": 100, "message": "Master export ready", "result_path": str(output)}
    publish_progress(job_id, payload)
    return payload

