from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from backend.config import settings
from backend.services.model_router import Provider, call_with_fallback

logger = logging.getLogger(__name__)

STAGE = "generation.voice"


async def _synthesize_async(text: str, out_path: Path, voice: str) -> Path:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out_path))
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError("edge-tts produced an empty audio file")
    return out_path


def _call_edge_tts(text: str, out_path: Path) -> Path:
    return asyncio.run(_synthesize_async(text, out_path, settings.edge_tts_voice))


def synthesize(text: str, out_path: Path) -> Path:
    providers = [
        Provider(name="edge-tts", call=lambda: _call_edge_tts(text, out_path)),
    ]
    return call_with_fallback(providers, stage=STAGE)
