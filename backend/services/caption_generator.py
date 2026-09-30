from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import numpy as np

from backend.config import settings
from backend.models.schemas import CaptionWord
from backend.services.model_router import Provider, call_with_fallback
from backend.utils.ffmpeg_utils import ffmpeg_path

logger = logging.getLogger(__name__)

STAGE = "generation.captions"

_WHISPER_SAMPLE_RATE = 16000

_model_cache: dict[str, object] = {}


def _load_model():
    name = settings.whisper_model
    if name not in _model_cache:
        from faster_whisper import WhisperModel

        _model_cache[name] = WhisperModel(name, device="cpu", compute_type="int8")
    return _model_cache[name]


def _decode_audio(audio_path: Path) -> np.ndarray:
    """Decode to 16kHz mono float32 PCM via the ffmpeg binary directly,
    bypassing faster-whisper's own av-based decoder - the installed `av`
    wheel on this Python/OS combo is ABI-incompatible with faster-whisper's
    expected API (no prebuilt wheel for an older, compatible av exists for
    this Python version, and building from source needs ffmpeg dev headers
    we don't have). Passing a numpy array to transcribe() skips av entirely.
    """
    cmd = [
        ffmpeg_path(),
        "-i", str(audio_path),
        "-f", "f32le",
        "-ac", "1",
        "-ar", str(_WHISPER_SAMPLE_RATE),
        "-loglevel", "error",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio decode failed: {result.stderr.decode(errors='replace').strip()}")

    return np.frombuffer(result.stdout, dtype=np.float32)


def _call_whisper(audio_path: Path) -> list[CaptionWord]:
    model = _load_model()
    audio = _decode_audio(audio_path)
    segments, _info = model.transcribe(audio, word_timestamps=True)

    words: list[CaptionWord] = []
    for segment in segments:
        for word in segment.words or []:
            token = str(word.word).strip()
            if not token:
                continue
            words.append(
                CaptionWord(
                    word=token,
                    start_seconds=float(word.start),
                    end_seconds=float(word.end),
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
