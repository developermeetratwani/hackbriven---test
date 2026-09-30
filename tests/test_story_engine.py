from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.core.exceptions import AllProvidersFailedError, InvalidScriptError
from backend.services import story_engine

VALID_JSON = json.dumps(
    {
        "hook": "EVs are taking over.",
        "mood": "upbeat",
        "scenes": [
            {"narration": "Cheaper to run.", "image_prompt": "ev charger", "duration_seconds": 4, "mood": "upbeat"},
            {"narration": "Better for the planet.", "image_prompt": "green forest and ev", "duration_seconds": 4, "mood": "hopeful"},
        ],
    }
)


def _mock_gemini_response(text: str) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": text}]}}]
    }
    return response


def _mock_groq_response(text: str) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"choices": [{"message": {"content": text}}]}
    return response


@patch("backend.services.story_engine.settings")
@patch("backend.services.story_engine.httpx.Client")
def test_generate_script_uses_gemini_when_available(mock_client_cls, mock_settings):
    mock_settings.gemini_api_key = "fake-key"
    mock_settings.groq_api_key = "fake-key"
    mock_settings.gemini_model = "gemini-1.5-flash"
    mock_settings.provider_timeout_seconds = 5.0

    client = MagicMock()
    client.post.return_value = _mock_gemini_response(VALID_JSON)
    mock_client_cls.return_value.__enter__.return_value = client

    script = story_engine.generate_script("Why EVs are popular")

    assert script.hook == "EVs are taking over."
    assert len(script.scenes) == 2
    assert script.scenes[0].index == 0


@patch("backend.services.story_engine.settings")
@patch("backend.services.story_engine.httpx.Client")
def test_generate_script_falls_back_to_groq_on_gemini_failure(mock_client_cls, mock_settings):
    mock_settings.gemini_api_key = "fake-key"
    mock_settings.groq_api_key = "fake-key"
    mock_settings.gemini_model = "gemini-1.5-flash"
    mock_settings.groq_model = "llama-3.1-70b-versatile"
    mock_settings.provider_timeout_seconds = 5.0

    client = MagicMock()

    def post_side_effect(url, **kwargs):
        if "generativelanguage" in url:
            raise RuntimeError("gemini rate limited")
        return _mock_groq_response(VALID_JSON)

    client.post.side_effect = post_side_effect
    mock_client_cls.return_value.__enter__.return_value = client

    script = story_engine.generate_script("Why EVs are popular")

    assert script.hook == "EVs are taking over."
    assert client.post.call_count == 2


@patch("backend.services.story_engine.settings")
def test_generate_script_raises_when_no_providers_configured(mock_settings):
    mock_settings.gemini_api_key = ""
    mock_settings.groq_api_key = ""

    with pytest.raises(AllProvidersFailedError):
        story_engine.generate_script("Why EVs are popular")


def test_parse_script_rejects_invalid_json():
    with pytest.raises(InvalidScriptError):
        story_engine._parse_script("topic", "not json at all")


def test_parse_script_rejects_zero_scenes():
    with pytest.raises(InvalidScriptError):
        story_engine._parse_script("topic", json.dumps({"hook": "h", "scenes": []}))
