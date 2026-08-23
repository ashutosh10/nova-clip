from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.entities import ClipStatus, JobKind, JobStatus, ProjectStatus

Prompt = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]


class ProjectCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None
    width: int = Field(default=1280, ge=256, le=1920, multiple_of=8)
    height: int = Field(default=720, ge=256, le=1080, multiple_of=8)
    fps: int = Field(default=24, ge=8, le=60)


class ProjectUpdate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "ProjectUpdate":
        if not self.model_fields_set:
            raise ValueError("Provide a project field to update")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        return self


class ClipGenerateRequest(BaseModel):
    prompt: Prompt
    position: int | None = Field(default=None, ge=0, le=1000)
    duration_seconds: float = Field(default=5.0, ge=1.0, le=5.0)
    generation_preset: Literal["fast", "balanced", "quality"] = "fast"
    inference_steps: int = Field(default=4, ge=4, le=60)
    guidance_scale: float = Field(default=5.0, ge=1.0, le=20.0)
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)


class VideoGenerateRequest(BaseModel):
    prompt: Prompt
    duration_seconds: Literal[5, 10, 15, 20, 30] = 10
    generation_preset: Literal["fast", "balanced", "quality"] = "fast"
    inference_steps: int = Field(default=4, ge=4, le=60)
    guidance_scale: float = Field(default=5.0, ge=1.0, le=20.0)
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)



class ClipTrimRequest(BaseModel):
    trim_start: float = Field(default=0, ge=0)
    trim_end: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> "ClipTrimRequest":
        if self.trim_end is not None and self.trim_end <= self.trim_start:
            raise ValueError("trim_end must be greater than trim_start")
        return self


class ReorderRequest(BaseModel):
    clip_ids: list[str] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def reject_duplicates(self) -> "ReorderRequest":
        if len(self.clip_ids) != len(set(self.clip_ids)):
            raise ValueError("clip_ids must not contain duplicates")
        return self


class StitchRequest(BaseModel):
    transition: Literal["cut", "crossfade"] = "cut"
    transition_seconds: float = Field(default=0.5, ge=0.1, le=3.0)
    codec: Literal["h264", "av1"] = "h264"


class ClipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    position: int
    prompt: str | None
    expanded_prompt: str | None
    media_url: str | None = None
    thumbnail_url: str | None = None
    duration_seconds: float | None
    trim_start: float
    trim_end: float | None
    status: ClipStatus
    error: str | None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str | None
    width: int
    height: int
    fps: int
    status: ProjectStatus
    master_url: str | None = None
    clips: list[ClipRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    clip_id: str | None
    kind: JobKind
    status: JobStatus
    progress: float
    current_step: int | None
    total_steps: int | None
    message: str
    eta_seconds: float | None
    speed: float | None
    result_url: str | None = None
    error: str | None
    created_at: datetime


class GenerateResponse(BaseModel):
    clip: ClipRead
    job: JobRead


class GenerateVideoResponse(BaseModel):
    clips: list[ClipRead]
    job: JobRead


