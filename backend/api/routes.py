from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from backend.core import credits
from backend.core.credits import InsufficientCreditsError
from backend.core.exceptions import JobNotFoundError
from backend.core.job_manager import JobManager
from backend.core.pipeline import run as run_pipeline
from backend.models.schemas import Job, MotionTier
from backend.services import payments
from backend.services.payments import PaymentError, SignatureVerificationError

router = APIRouter(prefix="/jobs", tags=["jobs"])
credits_router = APIRouter(prefix="/credits", tags=["credits"])
job_manager = JobManager()


class CreateJobRequest(BaseModel):
    topic: str
    motion_tier: MotionTier = MotionTier.BALANCED


@router.post("", response_model=Job)
def create_job(request: CreateJobRequest, background_tasks: BackgroundTasks) -> Job:
    topic = request.topic.strip()
    if not topic:
        raise HTTPException(status_code=422, detail="topic must not be empty")

    try:
        credits.charge(request.motion_tier, reason=f"job:{request.motion_tier.value}")
    except InsufficientCreditsError as exc:
        raise HTTPException(
            status_code=402,
            detail={
                "message": str(exc),
                "required": exc.required,
                "available": exc.available,
                "top_up": "/credits/create-order",
            },
        ) from exc

    job = job_manager.create(topic, motion_tier=request.motion_tier)
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


@credits_router.get("")
def get_credits() -> dict:
    return {"balance": credits.get_balance(), "cost_by_tier": {t.value: credits.cost_for_tier(t) for t in MotionTier}}


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@credits_router.post("/create-order")
def create_order() -> dict:
    try:
        return payments.create_order(receipt=f"topup_{uuid.uuid4().hex[:12]}")
    except PaymentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@credits_router.post("/verify-payment")
def verify_payment(request: VerifyPaymentRequest) -> dict:
    try:
        payments.verify_payment_signature(
            order_id=request.razorpay_order_id,
            payment_id=request.razorpay_payment_id,
            signature=request.razorpay_signature,
        )
    except SignatureVerificationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PaymentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    from backend.config import settings

    new_balance = credits.add_credits(
        settings.razorpay_package_credits,
        reason=f"razorpay:{request.razorpay_payment_id}",
    )
    return {"balance": new_balance}
