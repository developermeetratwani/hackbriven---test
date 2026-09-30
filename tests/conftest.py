from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from backend.models.schemas import CaptionWord, Scene, SceneAssets, Script


@pytest.fixture
def sample_script() -> Script:
    return Script(
        topic="Why electric vehicles are becoming popular",
        hook="EVs are taking over the roads. Here's why.",
        mood="upbeat",
        scenes=[
            Scene(index=0, narration="EVs cut fuel costs.", image_prompt="ev charging at home", duration_seconds=4.0),
            Scene(index=1, narration="Governments offer big incentives.", image_prompt="government building with ev sign", duration_seconds=5.0),
            Scene(index=2, narration="Battery range keeps improving.", image_prompt="ev on a highway at sunset", duration_seconds=3.5),
        ],
    )


@pytest.fixture
def sample_scene_assets(tmp_path: Path) -> list[SceneAssets]:
    assets = []
    for i in range(2):
        image_path = tmp_path / f"scene_{i}.png"
        audio_path = tmp_path / f"scene_{i}.mp3"
        image_path.write_bytes(b"fake-image-bytes")
        audio_path.write_bytes(b"fake-audio-bytes")
        assets.append(
            SceneAssets(
                index=i,
                image_path=str(image_path),
                audio_path=str(audio_path),
                caption_words=[
                    CaptionWord(word="hello", start_seconds=0.0 + i, end_seconds=0.4 + i),
                    CaptionWord(word="world", start_seconds=0.4 + i, end_seconds=0.8 + i),
                ],
                duration_seconds=4.0,
            )
        )
    return assets
