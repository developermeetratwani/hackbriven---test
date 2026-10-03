from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.config import settings
from backend.core import credits
from backend.core.credits import InsufficientCreditsError
from backend.core.exceptions import InvalidJobStateError, JobNotFoundError
from backend.core.job_manager import JobManager
from backend.core.pipeline import run as run_pipeline
from backend.models.schemas import Job, JobStatus, Language, MotionTier, QualityReport
from backend.services import payments, qoneqt_handoff
from backend.services.payments import PaymentError, SignatureVerificationError

router = APIRouter(prefix="/jobs", tags=["jobs"])
credits_router = APIRouter(prefix="/credits", tags=["credits"])
meta_router = APIRouter(tags=["meta"])
auth_router = APIRouter(prefix="/auth", tags=["auth"])
job_manager = JobManager()


def require_auth(authorization: str | None = Header(default=None)) -> None:
    """Shared-secret auth gate for mutating endpoints (PRD 6.9: "apply
    request limits and authenticated access to project/publishing
    endpoints"). A no-op when BACKEND_API_KEY isn't configured, which keeps
    local dev and the existing test suite working without a key - but that
    means auth is OFF by default and must be set before any real deploy;
    GET /providers/status surfaces whether it's on."""
    if not settings.has_auth:
        return
    expected = f"Bearer {settings.backend_api_key}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="missing or invalid Authorization header")


class LoginRequest(BaseModel):
    api_key: str = ""


@auth_router.post("/login")
def login(request: LoginRequest) -> dict:
    """Lets a frontend give immediate login feedback instead of discovering
    an invalid key only on the first job-creation attempt. This checks the
    same BACKEND_API_KEY require_auth() checks - it doesn't issue a session
    token, the frontend just holds onto the key client-side and resends it
    as the Authorization header on every mutating call, same as any other
    caller of this API."""
    if not settings.has_auth:
        return {"authenticated": True, "auth_required": False}
    if request.api_key == settings.backend_api_key:
        return {"authenticated": True, "auth_required": True}
    raise HTTPException(status_code=401, detail="invalid API key")


class CreateJobRequest(BaseModel):
    topic: str
    motion_tier: MotionTier = MotionTier.BALANCED
    language: Language = Language.EN


@router.post("", response_model=Job, dependencies=[Depends(require_auth)])
def create_job(
    request: CreateJobRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Job:
    topic = request.topic.strip()
    if not topic:
        raise HTTPException(status_code=422, detail="topic must not be empty")

    if idempotency_key:
        existing = job_manager.find_by_idempotency_key(idempotency_key)
        if existing is not None:
            # Same key already created a job - return it as-is, do not
            # charge credits or start a second pipeline run (PRD 6.6).
            return existing

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

    job = job_manager.create(
        topic, motion_tier=request.motion_tier, language=request.language, idempotency_key=idempotency_key
    )
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


@router.get("/{job_id}/quality-report", response_model=QualityReport)
def get_job_quality_report(job_id: str) -> QualityReport:
    try:
        job = job_manager.get(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if job.quality_report is None:
        raise HTTPException(status_code=409, detail="quality report not available yet")

    return job.quality_report


class ApproveRequest(BaseModel):
    approver: str = "unknown"


@router.post("/{job_id}/approve", response_model=Job, dependencies=[Depends(require_auth)])
def approve_job(job_id: str, request: ApproveRequest) -> Job:
    try:
        return job_manager.approve(job_id, approver=request.approver)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidJobStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{job_id}/cancel", response_model=Job, dependencies=[Depends(require_auth)])
def cancel_job(job_id: str) -> Job:
    try:
        return job_manager.cancel(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidJobStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{job_id}/publish", response_model=Job, dependencies=[Depends(require_auth)])
def publish_job(job_id: str) -> Job:
    """Qoneqt has no public creator-publishing API (confirmed from the
    client's own creator roster spreadsheet), so this always performs the
    honest manual handoff described in qoneqt_handoff.py and sets status to
    MANUAL_HANDOFF - never PUBLISHED, per PRD 6.7: "do not claim successful
    publishing until the platform confirms success."
    """
    try:
        job = job_manager.get(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if job.status != JobStatus.APPROVED:
        raise HTTPException(
            status_code=409,
            detail=f"job {job_id} must be approved before publishing (current status: {job.status.value})",
        )

    job_dir = settings.storage_path / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    try:
        note_path, note_text = qoneqt_handoff.build_handoff(job, job_dir)
    except Exception as exc:  # noqa: BLE001 - surface as a publish failure, not a 500
        return job_manager.update(
            job_id,
            status=JobStatus.PUBLISH_FAILED,
            publish_error=str(exc),
        )

    return job_manager.update(
        job_id,
        status=JobStatus.MANUAL_HANDOFF,
        manual_handoff_path=str(note_path),
        manual_handoff_note=note_text,
    )


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

    new_balance = credits.add_credits(
        settings.razorpay_package_credits,
        reason=f"razorpay:{request.razorpay_payment_id}",
    )
    return {"balance": new_balance}


@meta_router.get("/providers/status")
def providers_status() -> dict:
    """Which providers are configured per pipeline stage, without exposing
    any secret values (PRD 6.9 + 8: 'configured provider capabilities
    without exposing secrets'). This is also the "AI orchestra" view: each
    stage lists its fallback chain in the exact order call_with_fallback
    tries them, so it's visible that losing one provider doesn't stop the
    pipeline."""
    return {
        "script": {
            "chain": ["gemini", "groq", "openrouter", "local_template"],
            "configured": {
                "gemini": bool(settings.gemini_api_key),
                "groq": bool(settings.groq_api_key),
                "openrouter": bool(settings.openrouter_api_key),
                "local_template": True,
            },
        },
        "image": {
            "chain": ["nvidia", "pollinations", "placeholder"],
            "configured": {
                "nvidia": bool(settings.nvidia_api_key),
                "pollinations": True,
                "placeholder": True,
            },
        },
        "voice": {
            "chain": ["edge-tts", "gtts"],
            "configured": {"edge-tts": True, "gtts": True},
        },
        "captions": {
            "chain": ["groq_whisper", "local_whisper"],
            "configured": {
                "groq_whisper": bool(settings.groq_api_key),
                "local_whisper": True,
            },
        },
        "motion": {
            "chain": ["eightscale", "magic_hour", "ken_burns"],
            "configured": {
                "eightscale": bool(settings.eightscale_key_pool),
                "magic_hour": bool(settings.magic_hour_key_pool),
                "ken_burns": True,
            },
            "key_pool_size": {
                "eightscale": len(settings.eightscale_key_pool),
                "magic_hour": len(settings.magic_hour_key_pool),
            },
        },
        "payments": {"razorpay_configured": settings.has_razorpay},
        "persistence": {"mongodb_configured": bool(settings.mongodb_uri)},
        "auth": {"enabled": settings.has_auth},
    }


@meta_router.get("/analytics/overview")
def analytics_overview() -> dict:
    """Internal workflow metrics only (PRD 6.8: "clearly distinguish
    internal workflow metrics from Qoneqt viewership metrics" - we have no
    access to real Qoneqt viewership data, so none is shown or fabricated
    here)."""
    jobs = job_manager.list()
    by_status: dict[str, int] = {}
    for job in jobs:
        by_status[job.status.value] = by_status.get(job.status.value, 0) + 1

    return {
        "total_jobs": len(jobs),
        "by_status": by_status,
        "note": "internal workflow metrics only - no Qoneqt viewership data is available or shown",
    }


@meta_router.get("/ready")
def ready() -> JSONResponse:
    """Readiness check: can this process actually do work, not just answer
    HTTP (PRD 11 Observability: 'health/readiness endpoints')."""
    checks: dict[str, bool] = {}

    try:
        from backend.utils.ffmpeg_utils import ffmpeg_path

        ffmpeg_path()
        checks["ffmpeg"] = True
    except Exception:  # noqa: BLE001
        checks["ffmpeg"] = False

    if settings.mongodb_uri:
        try:
            import pymongo

            client = pymongo.MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=3000)
            client.admin.command("ping")
            checks["mongodb"] = True
        except Exception:  # noqa: BLE001
            checks["mongodb"] = False
    else:
        checks["mongodb"] = None  # not configured - in-memory/SQLite mode, not a failure

    ready_state = checks["ffmpeg"] and checks["mongodb"] is not False
    status_code = 200 if ready_state else 503
    return JSONResponse(status_code=status_code, content={"ready": ready_state, "checks": checks})
