from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    openrouter_api_key: str = ""
    openrouter_model: str = "nvidia/nemotron-3-super-120b-a12b:free"

    nvidia_api_key: str = ""
    nvidia_image_model: str = "black-forest-labs/flux.1-dev"

    edge_tts_voice: str = "en-US-AriaNeural"

    whisper_model: str = "base"

    fal_api_key: str = ""
    fal_motion_model: str = "fal-ai/ltx-video"

    magic_hour_api_key: str = ""
    magic_hour_resolution: str = "480p"
    # Real generative video is credit-metered (free tier: 400 credits,
    # ~120/5s clip at 480p) - cap how many scenes per job use it so one
    # video can't silently burn through the whole balance. Remaining
    # scenes fall back to Ken Burns, same resilience pattern as every
    # other stage.
    magic_hour_max_scenes_per_job: int = 2

    # Razorpay: client-facing credit top-ups. Use a rzp_test_ key first -
    # test mode charges nothing real and is otherwise identical.
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    # One top-up package: pay this many paise (INR x100), receive this many
    # platform credits. Placeholder pricing - adjust freely, the payment
    # mechanism doesn't depend on these numbers.
    razorpay_package_amount_paise: int = 9900  # ₹99
    razorpay_package_credits: int = 50

    # Credits ledger backing store. When set, backend/core/credits.py uses
    # this MongoDB instead of a local SQLite file - needed because this
    # pipeline is designed to deploy on Hugging Face Spaces, whose storage
    # is typically ephemeral (wiped on redeploy/restart), which would lose
    # a real paying balance. SQLite remains the fallback for local dev with
    # no URI configured.
    mongodb_uri: str = ""
    mongodb_db_name: str = "citysetu"

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

    @property
    def has_razorpay(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret)


settings = Settings()
