from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-70b-versatile"

    nvidia_api_key: str = ""
    nvidia_sd_model: str = "stabilityai/stable-diffusion-3.5-large"

    edge_tts_voice: str = "en-US-AriaNeural"

    whisper_model: str = "base"

    fal_api_key: str = ""
    fal_motion_model: str = "fal-ai/ltx-video"

    storage_dir: str = "storage/jobs"
    target_width: int = 1080
    target_height: int = 1920
    max_regenerate_attempts: int = 2

    provider_timeout_seconds: float = 30.0

    @property
    def storage_path(self) -> Path:
        path = Path(self.storage_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def has_fal(self) -> bool:
        return bool(self.fal_api_key)


settings = Settings()
