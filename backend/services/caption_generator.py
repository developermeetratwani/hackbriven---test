from __future__ import annotations

import logging
from pathlib import Path

from backend.config import settings
from backend.models.schemas import CaptionWord
from backend.services.model_router import Provider, call_with_fallback

logger = logging.getLogger(__name__)

STAGE = "generation.captions"

_model_cache: dict[str, object] = {}


def _load_model():
    name = settings.whisper_model
    if name not in _model_cache:
        import whisper

        _model_cache[name] = whisper.load_model(name)
    return _model_cache[name]


def _call_whisper(audio_path: Path) -> list[CaptionWord]:
    model = _load_model()
    result = model.transcribe(str(audio_path), word_timestamps=True)

    words: list[CaptionWord] = []
    for segment in result.get("segments", []):
        for word in segment.get("words", []):
            token = str(word.get("word", "")).strip()
            if not token:
                continue
            words.append(
                CaptionWord(
                    word=token,
                    start_seconds=float(word["start"]),
                    end_seconds=float(word["end"]),
                )
            )

    if not words:
        raise RuntimeError("whisper produced no word-level timestamps")
    return words


def transcribe(audio_path: Path) -> list[CaptionWord]:
    providers = [
        Provider(name="whisper", call=lambda: _call_whisper(audio_path)),
    ]
    return call_with_fallback(providers, stage=STAGE)
