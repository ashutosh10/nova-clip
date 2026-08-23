from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "Nova Clip API"
    environment: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite+aiosqlite:///./nova_clip.db"
    redis_url: str = "redis://localhost:6379/0"
    media_root: Path = Path("./media")
    public_media_url: str = "/media"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    llm_provider: Literal["ollama", "openai", "disabled"] = "ollama"
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "qwen2.5:7b"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    generation_backend: Literal["wan", "cogvideox", "mock"] = "wan"
    video_model_id: str = "Wan-AI/Wan2.1-T2V-14B-Diffusers"
    video_transformer_uri: str = "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/blob/main/split_files/diffusion_models/wan2.1_t2v_14B_fp8_e4m3fn.safetensors"
    wan_fp8: bool = True
    wan_vace_transformer_uri: str = "https://huggingface.co/Kamikaze-88/Wan2.1-VACE-14B-fp8/blob/main/wan2.1_vace_14B_fp8_e4m3fn.safetensors"
    wan_continuity_frames: int = Field(default=5, ge=1, le=5)
    wan_vace_fast_steps: int = Field(default=12, ge=8, le=50)
    wan_vace_balanced_steps: int = Field(default=18, ge=8, le=50)
    wan_vace_quality_steps: int = Field(default=30, ge=8, le=50)
    wan_offload_mode: Literal["model", "group", "none"] = "model"
    wan_lightx2v_repo: str = "lightx2v/Wan2.1-Distill-Loras"
    wan_lightx2v_t2v_weight: str = "wan2.1_t2v_14b_lora_rank64_lightx2v_4step.safetensors"
    model_cpu_offload: bool = True
    model_cache_dir: Path = Path("/models")
    gpu_lock_timeout_seconds: int = 21600

    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    ffmpeg_hardware_encoder: Literal["auto", "nvenc", "cpu"] = "auto"
    export_crf: int = Field(default=18, ge=0, le=51)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

