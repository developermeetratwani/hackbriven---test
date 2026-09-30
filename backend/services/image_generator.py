from __future__ import annotations

import base64
import logging
from pathlib import Path
from urllib.parse import quote

import httpx

from backend.config import settings
from backend.services.model_router import Provider, call_with_fallback

logger = logging.getLogger(__name__)

STAGE = "generation.image"


def _call_nvidia(prompt: str, out_path: Path) -> Path:
    if not settings.nvidia_api_key:
        raise RuntimeError("NVIDIA_API_KEY not configured")

    url = f"https://ai.api.nvidia.com/v1/genai/{settings.nvidia_sd_model}"
    headers = {
        "Authorization": f"Bearer {settings.nvidia_api_key}",
        "Accept": "application/json",
    }
    payload = {
        "prompt": prompt,
        "width": settings.target_width,
        "height": settings.target_height,
    }
    with httpx.Client(timeout=settings.provider_timeout_seconds) as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        body = response.json()

    image_b64 = body.get("image") or body["artifacts"][0]["base64"]
    out_path.write_bytes(base64.b64decode(image_b64))
    return out_path


def _call_pollinations(prompt: str, out_path: Path) -> Path:
    encoded_prompt = quote(prompt)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded_prompt}"
        f"?width={settings.target_width}&height={settings.target_height}&nologo=true"
    )
    with httpx.Client(timeout=settings.provider_timeout_seconds, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        content = response.content

    if not content:
        raise RuntimeError("pollinations returned empty image body")

    out_path.write_bytes(content)
    return out_path


def generate_image(prompt: str, out_path: Path) -> Path:
    providers = [
        Provider(name="nvidia_sd35", call=lambda: _call_nvidia(prompt, out_path)),
        Provider(name="pollinations", call=lambda: _call_pollinations(prompt, out_path)),
    ]
    return call_with_fallback(providers, stage=STAGE)
