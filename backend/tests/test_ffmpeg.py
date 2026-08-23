from pathlib import Path

import pytest

from app.services.ffmpeg import ClipInput, MediaProcessingError, stitch_clips


def test_stitch_requires_at_least_one_clip(tmp_path: Path) -> None:
    with pytest.raises(MediaProcessingError, match="At least one"):
        stitch_clips([], tmp_path / "master.mp4", 1280, 720, 24)


def test_stitch_rejects_missing_input(tmp_path: Path) -> None:
    with pytest.raises(MediaProcessingError, match="does not exist"):
        stitch_clips([ClipInput(tmp_path / "missing.mp4")], tmp_path / "master.mp4", 1280, 720, 24)

