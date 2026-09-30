from __future__ import annotations

import pytest

from backend.core.exceptions import JobNotFoundError
from backend.core.job_manager import JobManager
from backend.models.schemas import JobStatus


def test_create_and_get_job() -> None:
    manager = JobManager()
    job = manager.create("a topic")
    fetched = manager.get(job.id)
    assert fetched.id == job.id
    assert fetched.topic == "a topic"
    assert fetched.status == JobStatus.QUEUED


def test_get_missing_job_raises() -> None:
    manager = JobManager()
    with pytest.raises(JobNotFoundError):
        manager.get("does-not-exist")


def test_set_status_appends_history() -> None:
    manager = JobManager()
    job = manager.create("topic")
    manager.set_status(job.id, JobStatus.RUNNING_INTELLIGENCE)
    updated = manager.get(job.id)
    assert updated.status == JobStatus.RUNNING_INTELLIGENCE
    assert len(updated.history) == 2  # input accepted + status change


def test_mark_failed_sets_stage_and_reason() -> None:
    manager = JobManager()
    job = manager.create("topic")
    manager.mark_failed(job.id, stage="generation.image", reason="all providers failed")
    updated = manager.get(job.id)
    assert updated.status == JobStatus.FAILED
    assert updated.error_stage == "generation.image"
    assert updated.error_reason == "all providers failed"


def test_list_returns_all_jobs() -> None:
    manager = JobManager()
    manager.create("a")
    manager.create("b")
    assert len(manager.list()) == 2
