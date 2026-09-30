from __future__ import annotations

import threading

from backend.core.exceptions import JobNotFoundError
from backend.models.schemas import Job, JobStatus, StageTimestamp


class JobManager:
    """In-memory, thread-safe job store. No database, per PRD/TECH.md."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, topic: str) -> Job:
        job = Job(topic=topic)
        job.history.append(StageTimestamp(stage="input", status="accepted"))
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        return job

    def list(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def set_status(self, job_id: str, status: JobStatus, *, note: str = "") -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            job.status = status
            job.history.append(
                StageTimestamp(stage=status.value, status=note or "entered")
            )
            job.touch()
            return job

    def mark_failed(self, job_id: str, *, stage: str, reason: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            job.status = JobStatus.FAILED
            job.error_stage = stage
            job.error_reason = reason
            job.history.append(StageTimestamp(stage=stage, status=f"failed: {reason}"))
            job.touch()
            return job

    def update(self, job_id: str, **fields: object) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            for key, value in fields.items():
                setattr(job, key, value)
            job.touch()
            return job
