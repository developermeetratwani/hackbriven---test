from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from backend.core.exceptions import AllProvidersFailedError
from backend.services import caption_generator


def _fake_word(word: str, start: float, end: float) -> SimpleNamespace:
    return SimpleNamespace(word=word, start=start, end=end)


def _fake_segment(words: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(words=words)


@patch("backend.services.caption_generator._decode_audio")
@patch("backend.services.caption_generator._load_model")
def test_call_whisper_returns_word_level_captions(mock_load_model, mock_decode, tmp_path: Path):
    mock_decode.return_value = np.zeros(16000, dtype=np.float32)
    model = MagicMock()
    model.transcribe.return_value = (
        [_fake_segment([_fake_word("hello", 0.0, 0.4), _fake_word("world", 0.4, 0.9)])],
        object(),
    )
    mock_load_model.return_value = model

    words = caption_generator.transcribe(tmp_path / "audio.mp3")

    assert [w.word for w in words] == ["hello", "world"]
    assert words[0].start_seconds == 0.0
    assert words[1].end_seconds == 0.9


@patch("backend.services.caption_generator._decode_audio")
@patch("backend.services.caption_generator._load_model")
def test_call_whisper_skips_blank_words(mock_load_model, mock_decode, tmp_path: Path):
    mock_decode.return_value = np.zeros(16000, dtype=np.float32)
    model = MagicMock()
    model.transcribe.return_value = (
        [_fake_segment([_fake_word("  ", 0.0, 0.1), _fake_word("hi", 0.1, 0.3)])],
        object(),
    )
    mock_load_model.return_value = model

    words = caption_generator.transcribe(tmp_path / "audio.mp3")

    assert [w.word for w in words] == ["hi"]


@patch("backend.services.caption_generator._decode_audio")
@patch("backend.services.caption_generator._load_model")
def test_call_whisper_raises_when_no_words_produced(mock_load_model, mock_decode, tmp_path: Path):
    mock_decode.return_value = np.zeros(16000, dtype=np.float32)
    model = MagicMock()
    model.transcribe.return_value = ([_fake_segment([])], object())
    mock_load_model.return_value = model

    with pytest.raises(AllProvidersFailedError):
        caption_generator.transcribe(tmp_path / "audio.mp3")


@patch("backend.services.caption_generator.subprocess.run")
@patch("backend.services.caption_generator.ffmpeg_path", return_value="/fake/ffmpeg")
def test_decode_audio_invokes_ffmpeg_and_parses_pcm(mock_ffmpeg_path, mock_run, tmp_path: Path):
    fake_samples = np.array([0.1, -0.2, 0.3], dtype=np.float32)
    mock_run.return_value = MagicMock(returncode=0, stdout=fake_samples.tobytes())

    result = caption_generator._decode_audio(tmp_path / "audio.mp3")

    np.testing.assert_allclose(result, fake_samples)
    args = mock_run.call_args[0][0]
    assert args[0] == "/fake/ffmpeg"
    assert "-ar" in args and "16000" in args


@patch("backend.services.caption_generator.subprocess.run")
@patch("backend.services.caption_generator.ffmpeg_path", return_value="/fake/ffmpeg")
def test_decode_audio_raises_on_ffmpeg_failure(mock_ffmpeg_path, mock_run, tmp_path: Path):
    mock_run.return_value = MagicMock(returncode=1, stderr=b"boom")

    with pytest.raises(RuntimeError, match="ffmpeg audio decode failed"):
        caption_generator._decode_audio(tmp_path / "audio.mp3")
