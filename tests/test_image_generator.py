from __future__ import annotations

import base64
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from PIL import Image

from backend.services import image_generator


def _fake_jpeg_bytes(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(120, 180, 240)).save(buf, format="JPEG")
    return buf.getvalue()


def _fake_square_jpeg_bytes(size: int = 1920) -> bytes:
    return _fake_jpeg_bytes(size, size)


@pytest.fixture(autouse=True)
def _reset_pollinations_pacing():
    image_generator._pollinations_last_call_at = 0.0
    yield
    image_generator._pollinations_last_call_at = 0.0


@patch("backend.services.image_generator.settings")
@patch("backend.services.image_generator.httpx.Client")
def test_generate_image_uses_nvidia_when_available(mock_client_cls, mock_settings, tmp_path: Path):
    mock_settings.nvidia_api_key = "fake-key"
    mock_settings.nvidia_image_model = "black-forest-labs/flux.1-dev"
    mock_settings.target_width = 1080
    mock_settings.target_height = 1920
    mock_settings.provider_timeout_seconds = 5.0

    # NVIDIA's hosted models only accept enumerated dimensions (live-confirmed
    # with FLUX.1-dev), so _call_nvidia requests a fixed non-target size and
    # center-crops - the fake response must be a real decodable image, not
    # opaque bytes, and the saved output must end up at the target size.
    fake_image_bytes = _fake_jpeg_bytes(768, 1344)
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"image": base64.b64encode(fake_image_bytes).decode()}

    client = MagicMock()
    client.post.return_value = response
    mock_client_cls.return_value.__enter__.return_value = client

    out_path = tmp_path / "scene_00.png"
    result = image_generator.generate_image("ev charging at home", out_path)

    assert result == out_path
    with Image.open(out_path) as saved:
        assert saved.size == (1080, 1920)

    requested_payload = client.post.call_args.kwargs["json"]
    assert requested_payload["width"] == image_generator._NVIDIA_REQUEST_WIDTH
    assert requested_payload["height"] == image_generator._NVIDIA_REQUEST_HEIGHT


@patch("backend.services.image_generator.settings")
@patch("backend.services.image_generator.httpx.Client")
def test_generate_image_falls_back_to_pollinations(mock_client_cls, mock_settings, tmp_path: Path):
    mock_settings.nvidia_api_key = "fake-key"
    mock_settings.nvidia_image_model = "model"
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


def _http_402_error() -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://image.pollinations.ai/prompt/x")
    response = httpx.Response(402, request=request)
    return httpx.HTTPStatusError("402 Payment Required", request=request, response=response)


@patch("backend.services.image_generator.time.sleep")
@patch("backend.services.image_generator.settings")
@patch("backend.services.image_generator.httpx.Client")
def test_call_pollinations_retries_on_402_then_succeeds(mock_client_cls, mock_settings, mock_sleep, tmp_path: Path):
    mock_settings.target_width = 1080
    mock_settings.target_height = 1920
    mock_settings.provider_timeout_seconds = 5.0

    ok_response = MagicMock()
    ok_response.raise_for_status.return_value = None
    ok_response.content = _fake_square_jpeg_bytes(1920)

    client = MagicMock()

    def get_side_effect(*_args, **_kwargs):
        if client.get.call_count <= 2:
            raise _http_402_error()
        return ok_response

    client.get.side_effect = get_side_effect
    mock_client_cls.return_value.__enter__.return_value = client

    out_path = tmp_path / "scene_00.png"
    result = image_generator._call_pollinations("a red apple", out_path)

    assert result == out_path
    assert client.get.call_count == 3
    assert mock_sleep.call_count == 2


@patch("backend.services.image_generator.time.sleep")
@patch("backend.services.image_generator.settings")
@patch("backend.services.image_generator.httpx.Client")
def test_call_pollinations_gives_up_after_max_attempts(mock_client_cls, mock_settings, mock_sleep, tmp_path: Path):
    mock_settings.target_width = 1080
    mock_settings.target_height = 1920
    mock_settings.provider_timeout_seconds = 5.0

    client = MagicMock()
    client.get.side_effect = lambda *a, **k: (_ for _ in ()).throw(_http_402_error())
    mock_client_cls.return_value.__enter__.return_value = client

    with pytest.raises(httpx.HTTPStatusError):
        image_generator._call_pollinations("a red apple", tmp_path / "out.png")

    assert client.get.call_count == image_generator._POLLINATIONS_MAX_ATTEMPTS


@patch("backend.services.image_generator.time.sleep")
def test_pace_pollinations_skips_wait_on_first_call(mock_sleep):
    image_generator._pace_pollinations()
    mock_sleep.assert_not_called()


@patch("backend.services.image_generator.time.monotonic")
@patch("backend.services.image_generator.time.sleep")
def test_pace_pollinations_waits_out_the_remaining_interval(mock_sleep, mock_monotonic):
    # First call at t=1000 (well past the reset last_call_at=0, so no wait);
    # second call 2s later at t=1002 should sleep for the remaining 8s of
    # the 10s minimum interval.
    mock_monotonic.side_effect = [1000.0, 1000.0, 1002.0, 1002.0]
    image_generator._pace_pollinations()
    image_generator._pace_pollinations()
    mock_sleep.assert_called_once_with(pytest.approx(8.0))


@patch("backend.services.image_generator.settings")
@patch("backend.services.image_generator.httpx.Client")
def test_generate_image_falls_back_to_local_placeholder(mock_client_cls, mock_settings, tmp_path: Path):
    mock_settings.nvidia_api_key = "fake-key"
    mock_settings.nvidia_image_model = "model"
    mock_settings.target_width = 1080
    mock_settings.target_height = 1920
    mock_settings.provider_timeout_seconds = 5.0

    client = MagicMock()
    client.post.side_effect = RuntimeError("nvidia down")
    client.get.side_effect = RuntimeError("pollinations down")
    mock_client_cls.return_value.__enter__.return_value = client

    out_path = tmp_path / "out.png"
    result = image_generator.generate_image("a robot and a human shaking hands", out_path)

    assert result == out_path
    with Image.open(out_path) as saved:
        assert saved.size == (1080, 1920)


def test_prompt_to_gradient_is_deterministic():
    first = image_generator._prompt_to_gradient("a red apple")
    second = image_generator._prompt_to_gradient("a red apple")
    assert first == second


def test_prompt_to_gradient_differs_for_different_prompts():
    a = image_generator._prompt_to_gradient("a red apple")
    b = image_generator._prompt_to_gradient("a blue car")
    assert a != b


def test_generate_placeholder_produces_target_size(tmp_path: Path):
    out_path = tmp_path / "placeholder.png"
    result = image_generator._generate_placeholder("a robot and a human shaking hands", out_path)
    assert result == out_path
    with Image.open(out_path) as saved:
        assert saved.size == (1080, 1920)
