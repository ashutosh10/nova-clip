import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from app.core.config import settings

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[float, str], None]


class MediaProcessingError(RuntimeError):
    pass


@dataclass(frozen=True)
class ClipInput:
    path: Path
    trim_start: float = 0.0
    trim_end: float | None = None


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    logger.info("Running media command: %s", " ".join(command))
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise MediaProcessingError(f"Required executable not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc))[-4000:]
        raise MediaProcessingError(f"Media command failed: {detail}") from exc


def probe(path: Path) -> dict:
    result = _run([
        settings.ffprobe_binary, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)
    ])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaProcessingError(f"ffprobe returned invalid JSON for {path}") from exc


def duration(path: Path) -> float:
    metadata = probe(path)
    value = metadata.get("format", {}).get("duration")
    if value is None:
        raise MediaProcessingError(f"Could not determine duration for {path}")
    return float(value)


def _has_audio(metadata: dict) -> bool:
    return any(stream.get("codec_type") == "audio" for stream in metadata.get("streams", []))


def _video_encoder(codec: Literal["h264", "av1"] = "h264") -> tuple[str, list[str]]:
    mode = settings.ffmpeg_hardware_encoder
    if mode in {"auto", "nvenc"}:
        try:
            encoders = _run([settings.ffmpeg_binary, "-hide_banner", "-encoders"]).stdout
            requested = "av1_nvenc" if codec == "av1" else "h264_nvenc"
            if requested in encoders:
                return requested, ["-preset", "p6", "-cq", str(settings.export_crf)]
            if mode == "nvenc":
                raise MediaProcessingError(f"FFmpeg does not provide {requested}")
        except MediaProcessingError:
            if mode == "nvenc":
                raise
    if codec == "av1":
        return "libsvtav1", ["-preset", "6", "-crf", str(settings.export_crf + 8)]
    return "libx264", ["-preset", "slow", "-crf", str(settings.export_crf)]


def normalize_clip(
    clip: ClipInput, output: Path, width: int, height: int, fps: int, codec: Literal["h264", "av1"] = "h264"
) -> float:
    if not clip.path.is_file():
        raise MediaProcessingError(f"Clip does not exist: {clip.path}")
    metadata = probe(clip.path)
    source_duration = float(metadata.get("format", {}).get("duration", 0))
    end = clip.trim_end if clip.trim_end is not None else source_duration
    clip_duration = end - clip.trim_start
    if source_duration <= 0 or clip_duration <= 0 or end > source_duration + 0.05:
        raise MediaProcessingError(f"Invalid trim range for {clip.path.name}")

    output.parent.mkdir(parents=True, exist_ok=True)
    command = [settings.ffmpeg_binary, "-y", "-ss", f"{clip.trim_start:.4f}", "-t", f"{clip_duration:.4f}", "-i", str(clip.path)]
    audio_input = "0:a"
    if not _has_audio(metadata):
        command += ["-f", "lavfi", "-t", f"{clip_duration:.4f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        audio_input = "1:a"
    filters = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,fps={fps},"
        f"setsar=1,format=yuv420p,setpts=PTS-STARTPTS[v];"
        f"[{audio_input}]aformat=sample_rates=48000:channel_layouts=stereo,"
        f"atrim=duration={clip_duration:.4f},asetpts=PTS-STARTPTS[a]"
    )
    encoder, encoder_args = _video_encoder(codec)
    command += [
        "-filter_complex", filters, "-map", "[v]", "-map", "[a]", "-c:v", encoder, *encoder_args,
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(output)
    ]
    _run(command)
    return duration(output)


def create_thumbnail(source: Path, output: Path, at_seconds: float = 0.1) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    _run([
        settings.ffmpeg_binary, "-y", "-ss", f"{max(at_seconds, 0):.3f}", "-i", str(source),
        "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "3", str(output)
    ])


def stitch_clips(
    clips: list[ClipInput], output: Path, width: int, height: int, fps: int,
    transition: Literal["cut", "crossfade"] = "cut", transition_seconds: float = 0.5,
    codec: Literal["h264", "av1"] = "h264", progress: ProgressCallback | None = None,
) -> Path:
    if not clips:
        raise MediaProcessingError("At least one ready clip is required")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nova-stitch-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        normalized: list[Path] = []
        durations: list[float] = []
        for index, clip in enumerate(clips):
            if progress:
                progress((index / (len(clips) + 1)) * 75, f"Normalizing clip {index + 1}/{len(clips)}")
            normalized_path = temp_dir / f"clip-{index:04d}.mp4"
            durations.append(normalize_clip(clip, normalized_path, width, height, fps, codec))
            normalized.append(normalized_path)

        if progress:
            progress(80, "Combining normalized clips")
        if len(normalized) == 1:
            shutil.copy2(normalized[0], output)
        elif transition == "cut":
            concat_file = temp_dir / "concat.txt"
            concat_file.write_text(
                "".join(f"file '{str(path).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for path in normalized),
                encoding="utf-8",
            )
            _run([
                settings.ffmpeg_binary, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
                "-c", "copy", "-movflags", "+faststart", str(output)
            ])
        else:
            shortest = min(durations)
            if transition_seconds >= shortest:
                raise MediaProcessingError("Crossfade duration must be shorter than every trimmed clip")
            command = [settings.ffmpeg_binary, "-y"]
            for path in normalized:
                command += ["-i", str(path)]
            filter_parts: list[str] = []
            video_label, audio_label = "0:v", "0:a"
            elapsed = durations[0]
            for index in range(1, len(normalized)):
                next_video, next_audio = f"v{index}", f"a{index}"
                offset = elapsed - transition_seconds
                filter_parts.append(
                    f"[{video_label}][{index}:v]xfade=transition=fade:duration={transition_seconds:.4f}:offset={offset:.4f}[{next_video}]"
                )
                filter_parts.append(
                    f"[{audio_label}][{index}:a]acrossfade=d={transition_seconds:.4f}:c1=tri:c2=tri[{next_audio}]"
                )
                video_label, audio_label = next_video, next_audio
                elapsed += durations[index] - transition_seconds
            encoder, encoder_args = _video_encoder(codec)
            command += [
                "-filter_complex", ";".join(filter_parts), "-map", f"[{video_label}]", "-map", f"[{audio_label}]",
                "-c:v", encoder, *encoder_args, "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output)
            ]
            _run(command)
        if not output.is_file() or output.stat().st_size == 0:
            raise MediaProcessingError("FFmpeg completed without producing an output file")
        if progress:
            progress(100, "Master export ready")
    return output

