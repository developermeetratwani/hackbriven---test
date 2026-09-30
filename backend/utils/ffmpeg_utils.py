from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class FfmpegNotAvailableError(RuntimeError):
    pass


def run_ffmpeg(args: list[str], *, stage: str) -> None:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *args]
    logger.info("stage=%s running: %s", stage, " ".join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise FfmpegNotAvailableError("ffmpeg is not installed or not on PATH") from exc

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (stage={stage}): {result.stderr.strip()}")


def probe(path: Path) -> dict:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise FfmpegNotAvailableError("ffprobe is not installed or not on PATH") from exc

    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()}")

    return json.loads(result.stdout)
