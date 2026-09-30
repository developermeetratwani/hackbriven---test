from __future__ import annotations

import base64
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from backend.core.exceptions import AllProvidersFailedError
from backend.services import image_generator


def _fake_square_jpeg_bytes(size: int = 1920) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (size, size), color=(120, 180, 240)).save(buf, format="JPEG")
    return buf.getvalue()


@patch("backend.services.image_generator.settings")
@patch("backend.services.image_generator.httpx.Client")
def test_generate_image_uses_nvidia_when_available(mock_client_cls, mock_settings, tmp_path: Path):
    mock_settings.nvidia_api_key = "fake-key"
    mock_settings.nvidia_sd_model = "stabilityai/stable-diffusion-3.5-large"
    mock_settings.target_width = 1080
    mock_settings.target_height = 1920
    mock_settings.provider_timeout_seconds = 5.0

    fake_image_bytes = b"PNGDATA"
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"image": base64.b64encode(fake_image_bytes).decode()}

    client = MagicMock()
    client.post.return_value = response
    mock_client_cls.return_value.__enter__.return_value = client

    out_path = tmp_path / "scene_00.png"
    result = image_generator.generate_image("ev charging at home", out_path)

    assert result == out_path
    assert out_path.read_bytes() == fake_image_bytes


@patch("backend.services.image_generator.settings")
@patch("backend.services.image_generator.httpx.Client")
def test_generate_image_falls_back_to_pollinations(mock_client_cls, mock_settings, tmp_path: Path):
    mock_settings.nvidia_api_key = "fake-key"
    mock_settings.nvidia_sd_model = "model"
    mock_settings.target_width = 1080
    mock_settings.target_height = 1920
    mock_settings.provider_timeout_seconds = 5.0

    client = MagicMock()
    client.post.side_effect = RuntimeError("nvidia quota exceeded")

    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.content = _fake_square_jpeg_bytes(1920)
    client.get.return_value = fake_response

    mock_client_cls.return_value.__enter__.return_value = client

    out_path = tmp_path / "scene_00.png"
    result = image_generator.generate_image("ev charging at home", out_path)

    assert result == out_path
    with Image.open(out_path) as saved:
        assert saved.size == (1080, 1920)

    # Pollinations' free tier now 402s on any non-square size or nologo=true
    # (live-confirmed, undocumented) - request must stay square, no nologo.
    requested_url = client.get.call_args[0][0]
    assert "width=1920&height=1920" in requested_url
    assert "nologo" not in requested_url


def test_center_crop_produces_exact_target_size():
    square = Image.new("RGB", (1920, 1920))
    cropped = image_generator._center_crop(square, 1080, 1920)
    assert cropped.size == (1080, 1920)


def test_center_crop_is_centered_horizontally():
    # Left half red, right half blue; a centered crop of a square this wide
    # relative to the target should keep both halves partially visible.
    square = Image.new("RGB", (1920, 1920))
    for x in range(1920):
        for y in (0,):
            square.putpixel((x, y), (255, 0, 0) if x < 960 else (0, 0, 255))
    cropped = image_generator._center_crop(square, 1080, 1920)
    left_pixel = cropped.getpixel((0, 0))
    right_pixel = cropped.getpixel((1079, 0))
    assert left_pixel == (255, 0, 0)
    assert right_pixel == (0, 0, 255)


@patch("backend.services.image_generator.settings")
@patch("backend.services.image_generator.httpx.Client")
def test_generate_image_raises_when_all_providers_fail(mock_client_cls, mock_settings, tmp_path: Path):
    mock_settings.nvidia_api_key = "fake-key"
    mock_settings.nvidia_sd_model = "model"
    mock_settings.target_width = 1080
    mock_settings.target_height = 1920
    mock_settings.provider_timeout_seconds = 5.0

    client = MagicMock()
    client.post.side_effect = RuntimeError("nvidia down")
    client.get.side_effect = RuntimeError("pollinations down")
    mock_client_cls.return_value.__enter__.return_value = client

    with pytest.raises(AllProvidersFailedError):
        image_generator.generate_image("prompt", tmp_path / "out.png")
