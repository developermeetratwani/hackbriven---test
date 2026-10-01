from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

STAGE = "composition.motion"

_BASE_URL = "https://api.magichour.ai/v1"
_POLL_INTERVAL_SECONDS = 5.0
_POLL_TIMEOUT_SECONDS = 180.0


class MotionGenerationError(RuntimeError):
    pass


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.magic_hour_api_key}", "Content-Type": "application/json"}


def _upload_image(client: httpx.Client, image_path: Path) -> str:
    response = client.post(
        f"{_BASE_URL}/files/upload-urls",
        json={"items": [{"extension": "png", "type": "image"}]},
        headers=_headers(),
    )
    response.raise_for_status()
    item = response.json()["items"][0]
    upload_url, file_path = item["upload_url"], item["file_path"]

    put_response = client.put(upload_url, content=image_path.read_bytes(), headers={"Content-Type": "image/png"})
    put_response.raise_for_status()

    return file_path


def _create_job(client: httpx.Client, uploaded_file_path: str, prompt: str, duration_seconds: float) -> str:
    end_seconds = max(1, min(60, round(duration_seconds)))
    payload = {
        "end_seconds": end_seconds,
        "resolution": settings.magic_hour_resolution,
        "style": {"prompt": prompt},
        "assets": {"image_file_path": uploaded_file_path},
    }
    response = client.post(f"{_BASE_URL}/image-to-video", json=payload, headers=_headers())
    response.raise_for_status()
    return response.json()["id"]


def _poll_until_complete(client: httpx.Client, job_id: str) -> str:
    deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        response = client.get(f"{_BASE_URL}/video-projects/{job_id}", headers=_headers())
        response.raise_for_status()
        data = response.json()
        status = data.get("status")

        if status == "complete":
            download = data.get("download") or {}
            url = download.get("url")
            if not url:
                raise MotionGenerationError(f"magic hour job {job_id} completed with no download url")
            return url
        if status in ("error", "failed"):
            raise MotionGenerationError(f"magic hour job {job_id} failed: {data.get('error')}")

        time.sleep(_POLL_INTERVAL_SECONDS)

    raise MotionGenerationError(f"magic hour job {job_id} did not complete within {_POLL_TIMEOUT_SECONDS}s")


def generate_motion_clip(image_path: Path, prompt: str, duration_seconds: float, out_path: Path) -> Path:
    """Real generative image-to-video via Magic Hour (credit-metered; see
    settings.magic_hour_max_scenes_per_job). Returns the raw downloaded clip
    at whatever resolution/fps Magic Hour produced - callers must normalize
    it (resolution, fps, exact duration) to match the rest of the pipeline's
    clips before splicing it into the crossfade timeline.
    """
    if not settings.magic_hour_api_key:
        raise MotionGenerationError("MAGIC_HOUR_API_KEY not configured")

    with httpx.Client(timeout=settings.provider_timeout_seconds) as client:
        uploaded_file_path = _upload_image(client, image_path)
        job_id = _create_job(client, uploaded_file_path, prompt, duration_seconds)
        download_url = _poll_until_complete(client, job_id)

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        response = client.get(download_url)
        response.raise_for_status()
        if not response.content:
            raise MotionGenerationError(f"magic hour job {job_id} returned an empty video body")
        out_path.write_bytes(response.content)

    return out_path
