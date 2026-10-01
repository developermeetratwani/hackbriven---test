from __future__ import annotations

import logging
from pathlib import Path

from backend.config import settings
from backend.core.exceptions import PipelineError
from backend.core.job_manager import JobManager
from backend.models.schemas import JobStatus, SceneAssets, ScenePlanSet
from backend.services import (
    caption_generator,
    image_generator,
    quality_gate,
    scene_planner,
    story_engine,
    video_composer,
    voice_generator,
)
from backend.utils.ffmpeg_utils import get_duration_seconds

logger = logging.getLogger(__name__)


def _job_dir(job_id: str) -> Path:
    path = settings.storage_path / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _generate_scene_assets(job_id: str, plan: ScenePlanSet) -> list[SceneAssets]:
    job_dir = _job_dir(job_id)
    assets: list[SceneAssets] = []

    for scene in plan.scenes:
        image_path = job_dir / f"scene_{scene.index:02d}.png"
        audio_path = job_dir / f"scene_{scene.index:02d}.mp3"

        image_generator.generate_image(scene.image_prompt, image_path)
        voice_generator.synthesize(scene.narration, audio_path)
        caption_words = caption_generator.transcribe(audio_path)

        # The script's duration_seconds is only ever a guess (an LLM or the
        # local template estimating how long narration "should" take to
        # read); edge-tts's actual spoken-audio length is what the Ken Burns
        # clip and the final video must match, or video/audio drift out of
        # sync and the quality gate correctly rejects the result. Always
        # measure the real synthesized audio instead of trusting the guess.
        actual_duration = get_duration_seconds(audio_path)

        assets.append(
            SceneAssets(
                index=scene.index,
                image_path=str(image_path),
                audio_path=str(audio_path),
                caption_words=caption_words,
                duration_seconds=actual_duration,
                image_prompt=scene.image_prompt,
            )
        )

    return assets


def run(job_id: str, job_manager: JobManager, *, topic: str | None = None) -> None:
    """Run the full pipeline for a job: Intelligence -> Generation ->
    Composition -> Validation -> Output.

    Catches PipelineError at the boundary and marks the job FAILED with the
    stage + reason attached, per RULES.md #7. Any stage may raise it; nothing
    proceeds past a failed stage.
    """
    job = job_manager.get(job_id)
    resolved_topic = topic or job.topic

    try:
        job_manager.set_status(job_id, JobStatus.RUNNING_INTELLIGENCE)
        script = story_engine.generate_script(resolved_topic)
        plan = scene_planner.plan(script)
        job_manager.update(job_id, script=script, scene_plan=plan)

        job_manager.set_status(job_id, JobStatus.RUNNING_GENERATION)
        assets = _generate_scene_assets(job_id, plan)
        expected_duration = sum(asset.duration_seconds for asset in assets)

        job_manager.set_status(job_id, JobStatus.RUNNING_COMPOSITION)
        video_path = video_composer.compose(assets, _job_dir(job_id), motion_tier=job.motion_tier)

        job_manager.set_status(job_id, JobStatus.RUNNING_VALIDATION)
        report = quality_gate.check(video_path, expected_duration)

        attempts = 0
        while not report.passed and attempts < settings.max_regenerate_attempts:
            attempts += 1
            logger.warning(
                "job=%s quality gate failed (attempt %s): %s",
                job_id, attempts, report.reasons,
            )
            video_path = video_composer.compose(assets, _job_dir(job_id), motion_tier=job.motion_tier)
            report = quality_gate.check(video_path, expected_duration)

        job_manager.update(job_id, quality_report=report)

        if not report.passed:
            job_manager.mark_failed(
                job_id,
                stage="validation.quality_gate",
                reason="; ".join(report.reasons) or "quality gate failed",
            )
            return

        job_manager.update(job_id, result_path=str(video_path))
        job_manager.set_status(job_id, JobStatus.DONE)

    except PipelineError as exc:
        job_manager.mark_failed(job_id, stage=exc.stage, reason=exc.reason)
    except Exception as exc:  # noqa: BLE001 - last-resort boundary, never leak raw errors
        logger.exception("job=%s unexpected pipeline failure", job_id)
        job_manager.mark_failed(job_id, stage="pipeline", reason=str(exc))
