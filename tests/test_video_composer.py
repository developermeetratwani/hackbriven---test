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


def test_build_ass_captions_offsets_by_preceding_scene_durations(sample_scene_assets: list[SceneAssets], tmp_path: Path):
    # Whisper timestamps are local to each scene's own audio clip (start
    # near 0) - in the final concatenated video, scene 1's captions must
    # be shifted later by scene 0's full duration, or they land at the
    # wrong moment (confirmed live: every scene after the first was
    # restarting its captions at 0:00:00.00).
    out_path = tmp_path / "captions.ass"
    video_composer.build_ass_captions(sample_scene_assets, out_path)
    content = out_path.read_text(encoding="utf-8")

    scene0_duration = sample_scene_assets[0].duration_seconds
    scene1_word = sample_scene_assets[1].caption_words[0]
    expected_start = video_composer._ass_timestamp(scene0_duration + scene1_word.start_seconds)

    lines = [line for line in content.splitlines() if "Dialogue:" in line]
    # scene 0 contributes the first 2 lines (2 caption words), so scene 1's
    # first word is line index 2 - both scenes reuse the same word text
    # ("hello"/"world") in this fixture, so matching by text would find
    # scene 0's line instead.
    scene1_first_line = lines[len(sample_scene_assets[0].caption_words)]
    assert scene1_first_line.startswith(f"Dialogue: 0,{expected_start}")
    assert scene1_word.word in scene1_first_line


def test_build_ass_captions_sorts_out_of_order_scenes(sample_scene_assets: list[SceneAssets], tmp_path: Path):
    reversed_scenes = list(reversed(sample_scene_assets))
    out_path = tmp_path / "captions.ass"
    video_composer.build_ass_captions(reversed_scenes, out_path)
    content = out_path.read_text(encoding="utf-8")

    # Both scenes share the same word text ("hello"/"world") in this
    # fixture, so only the timestamp (not the word) distinguishes which
    # scene's line landed first - regardless of input order, scene 0 (the
    # lower index) must always be processed first, at offset 0.
    lines = [line for line in content.splitlines() if "Dialogue:" in line]
    expected_first_start = video_composer._ass_timestamp(
        sample_scene_assets[0].caption_words[0].start_seconds
    )
    assert lines[0].startswith(f"Dialogue: 0,{expected_first_start}")


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
