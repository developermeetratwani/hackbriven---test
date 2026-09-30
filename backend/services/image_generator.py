from __future__ import annotations

import base64
import hashlib
import io
import logging
import textwrap
import threading
import time
from pathlib import Path
from urllib.parse import quote

import httpx
from PIL import Image, ImageDraw, ImageFont

from backend.config import settings
from backend.services.model_router import Provider, call_with_fallback

logger = logging.getLogger(__name__)

STAGE = "generation.image"

_POLLINATIONS_RETRYABLE_STATUS = {402, 429, 503}
_POLLINATIONS_MAX_ATTEMPTS = 4
_POLLINATIONS_RETRY_DELAY_SECONDS = 8.0

# A pipeline job calls Pollinations once per scene, back-to-back - live
# testing showed that alone is enough to trip its free-tier rate limit
# (confirmed: identical requests fail then succeed seconds apart with no
# code change). Space calls out proactively so a job's own request burst
# doesn't trigger the limit in the first place; the retry above still
# covers genuinely external contention (other users hitting the same pool).
_POLLINATIONS_MIN_INTERVAL_SECONDS = 10.0
_pollinations_pacing_lock = threading.Lock()
_pollinations_last_call_at = 0.0


def _pace_pollinations() -> None:
    global _pollinations_last_call_at
    with _pollinations_pacing_lock:
        now = time.monotonic()
        wait = _POLLINATIONS_MIN_INTERVAL_SECONDS - (now - _pollinations_last_call_at)
        if wait > 0:
            time.sleep(wait)
        _pollinations_last_call_at = time.monotonic()


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
    height, then center-crop to the target vertical aspect ratio.

    Even square requests intermittently 402/429 under moderate call volume
    (live-confirmed: the exact same request failed, then succeeded seconds
    later with no code change) - a short retry-with-backoff absorbs that
    without escalating to the next provider in the chain unnecessarily.
    """
    size = settings.target_height
    encoded_prompt = quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={size}&height={size}"

    _pace_pollinations()

    content = b""
    last_error: Exception | None = None
    for attempt in range(1, _POLLINATIONS_MAX_ATTEMPTS + 1):
        try:
            with httpx.Client(timeout=settings.provider_timeout_seconds, follow_redirects=True) as client:
                response = client.get(url)
                response.raise_for_status()
                content = response.content
            last_error = None
            break
        except httpx.HTTPStatusError as exc:
            last_error = exc
            status = exc.response.status_code
            if status not in _POLLINATIONS_RETRYABLE_STATUS or attempt == _POLLINATIONS_MAX_ATTEMPTS:
                raise
            logger.warning(
                "pollinations attempt %s/%s got %s, retrying in %ss",
                attempt, _POLLINATIONS_MAX_ATTEMPTS, status, _POLLINATIONS_RETRY_DELAY_SECONDS,
            )
            time.sleep(_POLLINATIONS_RETRY_DELAY_SECONDS)

    if last_error is not None:
        raise last_error
    if not content:
        raise RuntimeError("pollinations returned empty image body")

    image = Image.open(io.BytesIO(content)).convert("RGB")
    cropped = _center_crop(image, settings.target_width, settings.target_height)
    cropped.save(out_path, format="PNG")
    return out_path


def _prompt_to_gradient(prompt: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    digest = hashlib.sha256(prompt.encode("utf-8")).digest()
    top = (80 + digest[0] % 120, 80 + digest[1] % 120, 80 + digest[2] % 120)
    bottom = tuple(max(0, c - 70) for c in top)
    return top, bottom


def _generate_placeholder(prompt: str, out_path: Path) -> Path:
    """Last-resort, fully offline image: a gradient card (color deterministically
    derived from the prompt, so scenes stay visually distinct) with the scene's
    image prompt rendered as centered text. Guarantees the Generation stage can
    never hard-fail for lack of a working external image API - same role as
    story_engine's local_template for the Intelligence stage."""
    width, height = settings.target_width, settings.target_height
    top, bottom = _prompt_to_gradient(prompt)

    image = Image.new("RGB", (width, height), top)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / height
        row = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (width, y)], fill=row)

    try:
        font = ImageFont.truetype("arial.ttf", 56)
    except OSError:
        font = ImageFont.load_default()

    wrapped = textwrap.fill(prompt, width=24)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=14, align="center")
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.multiline_text(
        ((width - text_w) // 2, (height - text_h) // 2),
        wrapped,
        font=font,
        fill=(255, 255, 255),
        align="center",
        spacing=14,
        stroke_width=3,
        stroke_fill=(0, 0, 0),
    )

    image.save(out_path, format="PNG")
    return out_path


def generate_image(prompt: str, out_path: Path) -> Path:
    providers = [
        Provider(name="nvidia_sd35", call=lambda: _call_nvidia(prompt, out_path)),
        Provider(name="pollinations", call=lambda: _call_pollinations(prompt, out_path)),
        Provider(name="local_placeholder", call=lambda: _generate_placeholder(prompt, out_path)),
    ]
    return call_with_fallback(providers, stage=STAGE)
