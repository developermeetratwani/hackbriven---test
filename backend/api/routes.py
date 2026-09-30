from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from backend.core.exceptions import JobNotFoundError
from backend.core.job_manager import JobManager
from backend.core.pipeline import run as run_pipeline
from backend.models.schemas import Job

router = APIRouter(prefix="/jobs", tags=["jobs"])
job_manager = JobManager()


class CreateJobRequest(BaseModel):
    topic: str


@router.post("", response_model=Job)
def create_job(request: CreateJobRequest, background_tasks: BackgroundTasks) -> Job:
    topic = request.topic.strip()
    if not topic:
        raise HTTPException(status_code=422, detail="topic must not be empty")

    job = job_manager.create(topic)
    background_tasks.add_task(run_pipeline, job.id, job_manager)
    return job


@router.get("", response_model=list[Job])
def list_jobs() -> list[Job]:
    return job_manager.list()


@router.get("/{job_id}", response_model=Job)
def get_job(job_id: str) -> Job:
    try:
        return job_manager.get(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{job_id}/result")
def get_job_result(job_id: str) -> dict:
    try:
        job = job_manager.get(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not job.result_path:
        raise HTTPException(status_code=409, detail="job has no result yet")

    return {"job_id": job_id, "result_path": job.result_path, "status": job.status}
