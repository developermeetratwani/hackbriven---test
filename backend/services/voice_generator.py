from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from backend.config import settings
from backend.models.schemas import Language
from backend.services.model_router import Provider, call_with_fallback

logger = logging.getLogger(__name__)

STAGE = "generation.voice"

_VOICE_BY_LANGUAGE = {
    Language.EN: lambda: settings.edge_tts_voice,
    Language.HI: lambda: settings.edge_tts_voice_hi,
    Language.HINGLISH: lambda: settings.edge_tts_voice_hinglish,
}


def _voice_for_language(language: Language) -> str:
    return _VOICE_BY_LANGUAGE[language]()


async def _synthesize_async(text: str, out_path: Path, voice: str) -> Path:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out_path))
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError("edge-tts produced an empty audio file")
    return out_path


def _call_edge_tts(text: str, out_path: Path, language: Language) -> Path:
    return asyncio.run(_synthesize_async(text, out_path, _voice_for_language(language)))


def synthesize(text: str, out_path: Path, *, language: Language = Language.EN) -> Path:
    providers = [
        Provider(name="edge-tts", call=lambda: _call_edge_tts(text, out_path, language)),
    ]
    return call_with_fallback(providers, stage=STAGE)
