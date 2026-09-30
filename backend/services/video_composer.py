from __future__ import annotations

import logging
from pathlib import Path

from backend.config import settings
from backend.core.exceptions import CompositionError
from backend.models.schemas import SceneAssets
from backend.utils.ffmpeg_utils import run_ffmpeg

logger = logging.getLogger(__name__)

STAGE = "composition"


def _ass_timestamp(seconds: float) -> str:
    total_centis = max(0, round(seconds * 100))
    hours, remainder = divmod(total_centis, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, centis = divmod(remainder, 100)
    return f"{hours:01d}:{minutes:02d}:{secs:02d}.{centis:02d}"


def build_ass_captions(scenes: list[SceneAssets], out_path: Path) -> Path:
    """Render word-synced karaoke-style captions as an .ass subtitle file.

    Pure/offline: no ffmpeg call, so this is directly unit-testable.
    """
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {settings.target_width}\n"
        f"PlayResY: {settings.target_height}\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, "
        "BackColour, Bold, Outline, Shadow, Alignment, MarginL, MarginR, MarginV\n"
        "Style: Caption,Arial,64,&H00FFFFFF,&H00000000,&H80000000,1,3,1,2,60,60,160\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Text\n"
    )

    lines: list[str] = []
    for scene in scenes:
        for word in scene.caption_words:
            start = _ass_timestamp(word.start_seconds)
            end = _ass_timestamp(word.end_seconds)
            lines.append(
                f"Dialogue: 0,{start},{end},Caption,{{\\b1}}{word.word}{{\\b0}}"
            )

    out_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def _build_scene_clip(image_path: Path, duration_seconds: float, out_path: Path) -> Path:
    width, height = settings.target_width, settings.target_height
    total_frames = max(1, round(duration_seconds * 25))
    zoompan = (
        f"scale={width * 2}:{height * 2},"
        f"zoompan=z='min(zoom+0.0015,1.15)':d={total_frames}:s={width}x{height}:fps=25,"
        f"format=yuv420p"
    )
    run_ffmpeg(
        [
            "-loop", "1",
            "-i", str(image_path),
            "-t", str(duration_seconds),
            "-vf", zoompan,
            str(out_path),
        ],
        stage=f"{STAGE}.ken_burns",
    )
    return out_path


def _concat_media(paths: list[Path], out_path: Path, list_file: Path) -> Path:
    list_file.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in paths), encoding="utf-8"
    )
    run_ffmpeg(
        ["-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(out_path)],
        stage=f"{STAGE}.concat",
    )
    return out_path


def compose(
    scenes: list[SceneAssets],
    job_dir: Path,
    *,
    music_path: Path | None = None,
) -> Path:
    """Combine per-scene images + audio + captions into one publish-ready MP4.

    Pipeline: Ken Burns per-scene clip -> concat video -> concat audio ->
    burn word-synced captions -> loudness-normalise (+ optional music ducking)
    -> H.264 export.
    """
    if not scenes:
        raise CompositionError(STAGE, "no scenes to compose")

    job_dir.mkdir(parents=True, exist_ok=True)
    scene_clip_paths: list[Path] = []
    for scene in sorted(scenes, key=lambda s: s.index):
        clip_path = job_dir / f"scene_{scene.index:02d}_clip.mp4"
        _build_scene_clip(Path(scene.image_path), scene.duration_seconds, clip_path)
        scene_clip_paths.append(clip_path)

    silent_video = job_dir / "silent.mp4"
    _concat_media(scene_clip_paths, silent_video, job_dir / "video_concat.txt")

    audio_paths = [Path(s.audio_path) for s in sorted(scenes, key=lambda s: s.index)]
    narration_audio = job_dir / "narration.wav"
    _concat_media(audio_paths, narration_audio, job_dir / "audio_concat.txt")

    captions_path = build_ass_captions(scenes, job_dir / "captions.ass")

    with_captions = job_dir / "with_captions.mp4"
    run_ffmpeg(
        [
            "-i", str(silent_video),
            "-vf", f"subtitles={captions_path.as_posix()}",
            "-an",
            str(with_captions),
        ],
        stage=f"{STAGE}.captions",
    )

    final_path = job_dir / "final.mp4"
    audio_filter = "loudnorm=I=-16:TP=-1.5:LRA=11"
    if music_path is not None:
        run_ffmpeg(
            [
                "-i", str(with_captions),
                "-i", str(narration_audio),
                "-i", str(music_path),
                "-filter_complex",
                f"[2:a]volume=0.25[music];"
                f"[1:a][music]sidechaincompress=threshold=0.05:ratio=8[ducked];"
                f"[1:a][ducked]amix=inputs=2:duration=first,{audio_filter}[aout]",
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "libx264",
                "-c:a", "aac",
                str(final_path),
            ],
            stage=f"{STAGE}.mix_duck",
        )
    else:
        run_ffmpeg(
            [
                "-i", str(with_captions),
                "-i", str(narration_audio),
                "-filter:a", audio_filter,
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "libx264",
                "-c:a", "aac",
                str(final_path),
            ],
            stage=f"{STAGE}.mix",
        )

    return final_path
