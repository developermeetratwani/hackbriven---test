from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from backend.models.schemas import SceneAssets
from backend.services import video_composer


def test_build_ass_captions_contains_every_word(sample_scene_assets: list[SceneAssets], tmp_path: Path):
    out_path = tmp_path / "captions.ass"
    video_composer.build_ass_captions(sample_scene_assets, out_path)

    content = out_path.read_text(encoding="utf-8")
    assert "hello" in content
    assert "world" in content
    assert "[Events]" in content
    assert content.count("Dialogue:") == 4  # 2 scenes x 2 words


def test_ass_timestamp_formats_correctly():
    assert video_composer._ass_timestamp(0.0) == "0:00:00.00"
    assert video_composer._ass_timestamp(65.5) == "0:01:05.50"


@patch("backend.services.video_composer.run_ffmpeg")
def test_compose_calls_ffmpeg_for_every_stage(mock_run_ffmpeg, sample_scene_assets: list[SceneAssets], tmp_path: Path):
    for asset in sample_scene_assets:
        Path(asset.audio_path).write_bytes(b"fake")
        Path(asset.image_path).write_bytes(b"fake")

    job_dir = tmp_path / "job"
    result = video_composer.compose(sample_scene_assets, job_dir)

    assert result == job_dir / "final.mp4"
    stages_called = [call.kwargs["stage"] for call in mock_run_ffmpeg.call_args_list]
    assert any("ken_burns" in s for s in stages_called)
    assert any("concat" in s for s in stages_called)
    assert any("captions" in s for s in stages_called)
    assert any("mix" in s for s in stages_called)


def test_compose_raises_on_empty_scenes(tmp_path: Path):
    from backend.core.exceptions import CompositionError
    import pytest

    with pytest.raises(CompositionError):
        video_composer.compose([], tmp_path)
