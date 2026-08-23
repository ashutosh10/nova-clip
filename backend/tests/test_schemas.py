import pytest
from pydantic import ValidationError

from app.schemas.api import ClipGenerateRequest, ClipTrimRequest, ProjectCreate, ReorderRequest


def test_project_dimensions_must_be_diffusion_safe() -> None:
    with pytest.raises(ValidationError):
        ProjectCreate(name="Demo", width=1279, height=720)


def test_generation_limits_are_enforced() -> None:
    with pytest.raises(ValidationError):
        ClipGenerateRequest(prompt="ok", duration_seconds=20, inference_steps=2)


def test_trim_end_must_follow_start() -> None:
    with pytest.raises(ValidationError):
        ClipTrimRequest(trim_start=2, trim_end=1)


def test_reorder_rejects_duplicate_ids() -> None:
    with pytest.raises(ValidationError):
        ReorderRequest(clip_ids=["a", "a"])

