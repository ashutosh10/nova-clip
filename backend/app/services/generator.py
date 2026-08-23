import gc
import logging
import math
import random
import subprocess
import time
from pathlib import Path
from typing import Callable

from app.core.config import settings

logger = logging.getLogger(__name__)
GenerationProgress = Callable[[int, int, float, float], None]
_pipeline = None
_pipeline_kind = None

WAN_NEGATIVE_PROMPT = (
    "Bright tones, overexposed, static, blurred details, subtitles, text, watermark, logo, "
    "paintings, still picture, overall gray, worst quality, low quality, JPEG artifacts, ugly, "
    "incomplete, extra fingers, poorly drawn hands, poorly drawn faces, deformed, disfigured, "
    "misshapen limbs, fused fingers, messy background, three legs, duplicated people, walking backwards"
)


class GenerationError(RuntimeError):
    pass


def _require_cuda():
    import torch

    if not torch.cuda.is_available():
        raise GenerationError("CUDA is unavailable; a supported NVIDIA GPU is required")
    return torch


def _clear_cuda_cache() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        logger.exception("CUDA cleanup failed")


def _offload_pipeline(pipeline, *, force: bool = False) -> None:
    if pipeline is None:
        return
    try:
        free_hooks = getattr(pipeline, "maybe_free_model_hooks", None)
        if callable(free_hooks):
            free_hooks()
    except Exception:
        logger.exception("Could not run pipeline offload hooks")

    if force:
        for component_name in ("text_encoder", "transformer", "vae"):
            component = getattr(pipeline, component_name, None)
            if component is None:
                continue
            try:
                component.to("cpu")
            except Exception:
                logger.exception("Could not move %s to CPU", component_name)


def _release_pipeline() -> None:
    global _pipeline, _pipeline_kind

    pipeline = _pipeline
    previous_kind = _pipeline_kind
    _pipeline = None
    _pipeline_kind = None
    if pipeline is not None:
        logger.info("Releasing %s pipeline and all CUDA allocations", previous_kind)
        _offload_pipeline(pipeline, force=True)
        del pipeline
    _clear_cuda_cache()


def _load_wan_pipeline():
    torch = _require_cuda()
    try:
        from diffusers import AutoencoderKLWan, WanPipeline, WanTransformer3DModel
        from transformers import UMT5EncoderModel

        dtype = torch.bfloat16
        torch.set_float32_matmul_precision("high")
        logger.info("Loading Wan transformer from %s", settings.video_transformer_uri)
        transformer = WanTransformer3DModel.from_single_file(
            settings.video_transformer_uri,
            torch_dtype=dtype,
            cache_dir=str(settings.model_cache_dir),
        )
        if settings.wan_fp8:
            transformer.enable_layerwise_casting(
                storage_dtype=torch.float8_e4m3fn,
                compute_dtype=dtype,
                non_blocking=True,
            )

        text_encoder = UMT5EncoderModel.from_pretrained(
            settings.video_model_id,
            subfolder="text_encoder",
            torch_dtype=dtype,
            cache_dir=str(settings.model_cache_dir),
        )
        vae = AutoencoderKLWan.from_pretrained(
            settings.video_model_id,
            subfolder="vae",
            torch_dtype=torch.float32,
            cache_dir=str(settings.model_cache_dir),
        )
        vae.enable_tiling()
        vae.enable_slicing()

        if settings.wan_offload_mode == "group":
            from diffusers.hooks import apply_group_offloading

            onload_device = torch.device("cuda")
            offload_device = torch.device("cpu")
            apply_group_offloading(
                text_encoder,
                onload_device=onload_device,
                offload_device=offload_device,
                offload_type="block_level",
                num_blocks_per_group=2,
            )
            transformer.enable_group_offload(
                onload_device=onload_device,
                offload_device=offload_device,
                offload_type="block_level",
                num_blocks_per_group=1,
                use_stream=True,
                record_stream=True,
                non_blocking=True,
            )

        pipeline = WanPipeline.from_pretrained(
            settings.video_model_id,
            transformer=transformer,
            text_encoder=text_encoder,
            vae=vae,
            torch_dtype=dtype,
            cache_dir=str(settings.model_cache_dir),
        )
        pipeline.load_lora_weights(
            settings.wan_lightx2v_repo,
            weight_name=settings.wan_lightx2v_t2v_weight,
            adapter_name="lightx2v",
            cache_dir=str(settings.model_cache_dir),
        )
        lora_parameter_count = 0
        for name, parameter in pipeline.transformer.named_parameters():
            if "lora_A" in name or "lora_B" in name:
                parameter.data = parameter.data.to(dtype=dtype)
                lora_parameter_count += parameter.numel()
        logger.info("Loaded LightX2V adapter with %d BF16 parameters", lora_parameter_count)
        if settings.wan_offload_mode == "model":
            # Component-level offloading transfers the FP8 transformer once,
            # then keeps it on the GPU for the complete denoising loop.
            pipeline.enable_model_cpu_offload()
        elif settings.wan_offload_mode == "group":
            pipeline.vae.to("cuda")
        else:
            pipeline.to("cuda")
        logger.info("Wan pipeline ready (offload_mode=%s)", settings.wan_offload_mode)
        return pipeline
    except Exception as exc:
        logger.exception("Could not load Wan video pipeline")
        if isinstance(exc, GenerationError):
            raise
        raise GenerationError(f"Could not load Wan model {settings.video_model_id}: {exc}") from exc

def _load_wan_vace_pipeline():
    torch = _require_cuda()
    try:
        from diffusers import (
            AutoencoderKLWan,
            FlowMatchEulerDiscreteScheduler,
            UniPCMultistepScheduler,
            WanVACEPipeline,
            WanVACETransformer3DModel,
        )
        from transformers import AutoTokenizer, UMT5EncoderModel

        dtype = torch.bfloat16
        logger.info("Loading Wan VACE transformer from %s", settings.wan_vace_transformer_uri)
        transformer = WanVACETransformer3DModel.from_single_file(
            settings.wan_vace_transformer_uri,
            torch_dtype=dtype,
            cache_dir=str(settings.model_cache_dir),
        )
        if settings.wan_fp8:
            transformer.enable_layerwise_casting(
                storage_dtype=torch.float8_e4m3fn,
                compute_dtype=dtype,
                non_blocking=True,
            )
        tokenizer = AutoTokenizer.from_pretrained(
            settings.video_model_id,
            subfolder="tokenizer",
            cache_dir=str(settings.model_cache_dir),
        )
        text_encoder = UMT5EncoderModel.from_pretrained(
            settings.video_model_id,
            subfolder="text_encoder",
            torch_dtype=dtype,
            cache_dir=str(settings.model_cache_dir),
        )
        vae = AutoencoderKLWan.from_pretrained(
            settings.video_model_id,
            subfolder="vae",
            torch_dtype=torch.float32,
            cache_dir=str(settings.model_cache_dir),
        )
        vae.enable_tiling()
        vae.enable_slicing()
        base_scheduler = FlowMatchEulerDiscreteScheduler.from_pretrained(
            settings.video_model_id,
            subfolder="scheduler",
            cache_dir=str(settings.model_cache_dir),
        )
        scheduler = UniPCMultistepScheduler.from_config(base_scheduler.config, flow_shift=3.0)
        pipeline = WanVACEPipeline(
            tokenizer=tokenizer,
            text_encoder=text_encoder,
            vae=vae,
            scheduler=scheduler,
            transformer=transformer,
        )
        if settings.wan_offload_mode == "none":
            pipeline.to("cuda")
        else:
            pipeline.enable_model_cpu_offload()
        logger.info("Wan VACE five-frame continuation pipeline ready")
        return pipeline
    except Exception as exc:
        logger.exception("Could not load Wan VACE continuation pipeline")
        if isinstance(exc, GenerationError):
            raise
        raise GenerationError(f"Could not load Wan VACE model: {exc}") from exc




def _load_cogvideox_pipeline():
    torch = _require_cuda()
    try:
        from diffusers import CogVideoXPipeline

        pipeline = CogVideoXPipeline.from_pretrained(
            settings.video_model_id,
            torch_dtype=torch.bfloat16,
            cache_dir=str(settings.model_cache_dir),
        )
        pipeline.vae.enable_tiling()
        pipeline.vae.enable_slicing()
        if settings.model_cpu_offload:
            pipeline.enable_model_cpu_offload()
        else:
            pipeline.to("cuda")
        return pipeline
    except Exception as exc:
        logger.exception("Could not load CogVideoX pipeline")
        raise GenerationError(f"Could not load {settings.video_model_id}: {exc}") from exc


def _load_pipeline(kind: str = "t2v"):
    global _pipeline, _pipeline_kind
    if _pipeline is not None and _pipeline_kind == kind:
        return _pipeline
    if _pipeline is not None:
        logger.info("Switching pipeline from %s to %s", _pipeline_kind, kind)
        _release_pipeline()
    if settings.generation_backend == "wan":
        _pipeline = _load_wan_vace_pipeline() if kind == "vace" else _load_wan_pipeline()
    elif settings.generation_backend == "cogvideox":
        _pipeline = _load_cogvideox_pipeline()
    else:
        raise GenerationError(f"Unsupported generation backend: {settings.generation_backend}")
    _pipeline_kind = kind
    return _pipeline


def _mock_video(output: Path, duration_seconds: float, width: int, height: int, fps: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        settings.ffmpeg_binary, "-y", "-f", "lavfi", "-i",
        f"color=c=0x111827:s={width}x{height}:r={fps}:d={duration_seconds}",
        "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={duration_seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(output),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)


def _wan_dimensions(width: int, height: int, preset: str = "quality") -> tuple[int, int]:
    # Each size is divisible by 16. Exports are normalized to the project canvas.
    landscape_sizes = {
        "fast": (480, 272),
        "balanced": (656, 368),
        "quality": (832, 480),
    }
    generation_width, generation_height = landscape_sizes.get(preset, landscape_sizes["quality"])
    if width >= height:
        return generation_width, generation_height
    return generation_height, generation_width


def _wan_frame_plan(duration_seconds: float, preset: str = "quality") -> tuple[int, int]:
    # Wan requires 4k+1 frames. Draft modes reduce temporal attention work.
    target_fps = {"fast": 8, "balanced": 12, "quality": 16}.get(preset, 16)
    max_intervals = {"fast": 40, "balanced": 60, "quality": 80}.get(preset, 80)
    intervals = min(max_intervals, max(16, round(duration_seconds * target_fps / 4) * 4))
    num_frames = intervals + 1
    generation_fps = max(4, round(intervals / duration_seconds))
    return num_frames, generation_fps

def _prepare_vace_conditions(
    source: Path, width: int, height: int, num_frames: int, continuity_frames: int = 5
):
    from PIL import Image
    from diffusers.utils import load_video

    frames = load_video(str(source))
    if len(frames) < continuity_frames:
        raise GenerationError(f"Continuation source has fewer than {continuity_frames} frames")
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    tail = [frame.convert("RGB").resize((width, height), resampling) for frame in frames[-continuity_frames:]]
    gray = Image.new("RGB", (width, height), (128, 128, 128))
    mask_black = Image.new("L", (width, height), 0)
    mask_white = Image.new("L", (width, height), 255)
    video = [*tail, *[gray.copy() for _ in range(num_frames - continuity_frames)]]
    mask = [
        *[mask_black.copy() for _ in range(continuity_frames)],
        *[mask_white.copy() for _ in range(num_frames - continuity_frames)],
    ]
    return video, mask




def _cogvideox_frame_plan(duration_seconds: float) -> tuple[int, int]:
    num_frames = min(49, max(9, int(math.floor(duration_seconds) * 8 + 1)))
    generation_fps = max(4, round((num_frames - 1) / duration_seconds))
    return num_frames, generation_fps


def generate_video(
    prompt: str, output: Path, duration_seconds: float, width: int, height: int, fps: int,
    inference_steps: int, guidance_scale: float, seed: int | None, progress: GenerationProgress,
    generation_preset: str = "quality",
    conditioning_video: Path | None = None,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    pipeline = None
    failed = False
    try:
        if settings.generation_backend == "mock":
            for step in range(1, inference_steps + 1):
                elapsed = max(time.monotonic() - started, 0.001)
                progress(step, inference_steps, step / elapsed, (inference_steps - step) / (step / elapsed))
            _mock_video(output, duration_seconds, width, height, fps)
            return output

        torch = _require_cuda()
        from diffusers.utils import export_to_video

        pipeline = _load_pipeline("vace" if conditioning_video is not None else "t2v")
        resolved_seed = seed if seed is not None else random.SystemRandom().randint(0, 2**32 - 1)
        generator = torch.Generator(device="cuda").manual_seed(resolved_seed)

        conditioned_video = condition_mask = None
        if settings.generation_backend == "wan":
            generation_width, generation_height = _wan_dimensions(width, height, generation_preset)
            num_frames, generation_fps = _wan_frame_plan(duration_seconds, generation_preset)
            if conditioning_video is not None:
                continuity_frames = settings.wan_continuity_frames
                num_frames += continuity_frames - 1
                vace_steps = {
                    "fast": settings.wan_vace_fast_steps,
                    "balanced": settings.wan_vace_balanced_steps,
                    "quality": settings.wan_vace_quality_steps,
                }.get(generation_preset, settings.wan_vace_quality_steps)
                inference_steps = max(inference_steps, vace_steps)
                guidance_scale = 5.0
                conditioned_video, condition_mask = _prepare_vace_conditions(
                    conditioning_video,
                    generation_width,
                    generation_height,
                    num_frames,
                    continuity_frames,
                )
            elif generation_preset in {"fast", "balanced"}:
                pipeline.set_adapters(["lightx2v"], adapter_weights=[1.0])
                pipeline.enable_lora()
                inference_steps = 4
                guidance_scale = 1.0
            else:
                pipeline.disable_lora()
        else:
            generation_width = generation_height = None
            num_frames, generation_fps = _cogvideox_frame_plan(duration_seconds)

        def callback(_pipe, step_index: int, _timestep, callback_kwargs: dict):
            completed = step_index + 1
            elapsed = max(time.monotonic() - started, 0.001)
            speed = completed / elapsed
            progress(completed, inference_steps, speed, max(0, inference_steps - completed) / max(speed, 0.001))
            return callback_kwargs

        pipeline_args = {
            "prompt": prompt,
            "num_inference_steps": inference_steps,
            "num_frames": num_frames,
            "guidance_scale": guidance_scale,
            "generator": generator,
            "callback_on_step_end": callback,
        }
        if settings.generation_backend == "wan":
            pipeline_args.update(
                negative_prompt=WAN_NEGATIVE_PROMPT,
                width=generation_width,
                height=generation_height,
            )
            if conditioning_video is not None:
                pipeline_args.update(
                    video=conditioned_video,
                    mask=condition_mask,
                    conditioning_scale=1.0,
                )
        else:
            pipeline_args["num_videos_per_prompt"] = 1

        result = pipeline(**pipeline_args)
        frames = result.frames[0]
        if conditioning_video is not None:
            frames = frames[settings.wan_continuity_frames:]
        export_to_video(frames, str(output), fps=generation_fps)
        if not output.is_file() or output.stat().st_size == 0:
            raise GenerationError("The model returned no video data")
        return output
    except Exception as exc:
        failed = True
        logger.exception("Video generation failed")
        if isinstance(exc, GenerationError):
            raise
        raise GenerationError(str(exc)) from exc
    finally:
        if failed:
            # An interrupted Accelerate hook can leave an entire component on
            # the GPU. Destroy the cached pipeline so the allocation is real,
            # rather than merely being hidden from the CUDA cache.
            _release_pipeline()
        else:
            # Successful calls are kept warm in host RAM, but no component is
            # allowed to remain resident in VRAM between clips.
            _offload_pipeline(pipeline, force=True)
            _clear_cuda_cache()
