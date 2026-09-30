from __future__ import annotations

import base64
import io
import logging
from pathlib import Path
from urllib.parse import quote

import httpx
from PIL import Image

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


def _center_crop(image: Image.Image, target_width: int, target_height: int) -> Image.Image:
    src_w, src_h = image.size
    scale = max(target_width / src_w, target_height / src_h)
    resized = image.resize((round(src_w * scale), round(src_h * scale)))
    rw, rh = resized.size
    left = (rw - target_width) // 2
    top = (rh - target_height) // 2
    return resized.crop((left, top, left + target_width, top + target_height))


def _call_pollinations(prompt: str, out_path: Path) -> Path:
    """Pollinations' free tier now only serves exact square (width == height)
    images with no `nologo` param - any other aspect ratio or the nologo
    flag returns 402 Payment Required (confirmed live, not documented
    anywhere at the time this was written). Request a square at our target
    height, then center-crop to the target vertical aspect ratio."""
    size = settings.target_height
    encoded_prompt = quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={size}&height={size}"
    with httpx.Client(timeout=settings.provider_timeout_seconds, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        content = response.content

    if not content:
        raise RuntimeError("pollinations returned empty image body")

    image = Image.open(io.BytesIO(content)).convert("RGB")
    cropped = _center_crop(image, settings.target_width, settings.target_height)
    cropped.save(out_path, format="PNG")
    return out_path


def generate_image(prompt: str, out_path: Path) -> Path:
    providers = [
        Provider(name="nvidia_sd35", call=lambda: _call_nvidia(prompt, out_path)),
        Provider(name="pollinations", call=lambda: _call_pollinations(prompt, out_path)),
    ]
    return call_with_fallback(providers, stage=STAGE)
