from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.core.exceptions import AllProvidersFailedError
from backend.services import image_generator


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
    fake_response.content = b"POLLINATIONS_IMAGE_BYTES"
    client.get.return_value = fake_response

    mock_client_cls.return_value.__enter__.return_value = client

    out_path = tmp_path / "scene_00.png"
    result = image_generator.generate_image("ev charging at home", out_path)

    assert result == out_path
    assert out_path.read_bytes() == b"POLLINATIONS_IMAGE_BYTES"


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
