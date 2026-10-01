from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.services import motion_generator


@patch("backend.services.motion_generator.settings")
@patch("backend.services.motion_generator.httpx.Client")
def test_generate_motion_clip_happy_path(mock_client_cls, mock_settings, tmp_path: Path):
    mock_settings.magic_hour_api_key = "fake-key"
    mock_settings.magic_hour_resolution = "480p"
    mock_settings.provider_timeout_seconds = 30.0

    upload_response = MagicMock()
    upload_response.raise_for_status.return_value = None
    upload_response.json.return_value = {
        "items": [{"upload_url": "https://upload.example/x", "file_path": "api-assets/x.png"}]
    }
    put_response = MagicMock()
    put_response.raise_for_status.return_value = None

    create_response = MagicMock()
    create_response.raise_for_status.return_value = None
    create_response.json.return_value = {"id": "job123"}

    poll_response = MagicMock()
    poll_response.raise_for_status.return_value = None
    poll_response.json.return_value = {
        "status": "complete",
        "download": {"url": "https://videos.example/job123/output.mp4"},
    }

    api_client = MagicMock()
    api_client.post.side_effect = [upload_response, create_response]
    api_client.put.return_value = put_response
    api_client.get.return_value = poll_response

    download_response = MagicMock()
    download_response.raise_for_status.return_value = None
    download_response.content = b"FAKE_VIDEO_BYTES"

    download_client = MagicMock()
    download_client.get.return_value = download_response

    mock_client_cls.return_value.__enter__.side_effect = [api_client, download_client]

    image_path = tmp_path / "scene.png"
    image_path.write_bytes(b"fake-image")
    out_path = tmp_path / "clip.mp4"

    result = motion_generator.generate_motion_clip(image_path, "a robot waving", 5.0, out_path)

    assert result == out_path
    assert out_path.read_bytes() == b"FAKE_VIDEO_BYTES"
    assert api_client.post.call_count == 2  # upload-urls, then image-to-video


@patch("backend.services.motion_generator.settings")
def test_generate_motion_clip_raises_without_key(mock_settings, tmp_path: Path):
    mock_settings.magic_hour_api_key = ""

    with pytest.raises(motion_generator.MotionGenerationError, match="not configured"):
        motion_generator.generate_motion_clip(tmp_path / "x.png", "prompt", 5.0, tmp_path / "out.mp4")


@patch("backend.services.motion_generator.time.sleep")
@patch("backend.services.motion_generator.time.monotonic")
def test_poll_until_complete_raises_on_error_status(mock_monotonic, mock_sleep):
    mock_monotonic.side_effect = [0.0, 1.0]
    client = MagicMock()
    error_response = MagicMock()
    error_response.raise_for_status.return_value = None
    error_response.json.return_value = {"status": "error", "error": "model timeout"}
    client.get.return_value = error_response

    with pytest.raises(motion_generator.MotionGenerationError, match="model timeout"):
        motion_generator._poll_until_complete(client, "job123")


@patch("backend.services.motion_generator.time.sleep")
@patch("backend.services.motion_generator.time.monotonic")
def test_poll_until_complete_times_out(mock_monotonic, mock_sleep):
    # monotonic() is called once per loop condition check; make it exceed
    # the deadline immediately after the first iteration's work.
    mock_monotonic.side_effect = [0.0, 0.0, 999999.0]
    client = MagicMock()
    rendering_response = MagicMock()
    rendering_response.raise_for_status.return_value = None
    rendering_response.json.return_value = {"status": "rendering"}
    client.get.return_value = rendering_response

    with pytest.raises(motion_generator.MotionGenerationError, match="did not complete"):
        motion_generator._poll_until_complete(client, "job123")


@patch("backend.services.motion_generator.settings")
def test_poll_until_complete_raises_when_no_download_url(mock_settings):
    client = MagicMock()
    complete_response = MagicMock()
    complete_response.raise_for_status.return_value = None
    complete_response.json.return_value = {"status": "complete", "download": None}
    client.get.return_value = complete_response

    with pytest.raises(motion_generator.MotionGenerationError, match="no download url"):
        motion_generator._poll_until_complete(client, "job123")
