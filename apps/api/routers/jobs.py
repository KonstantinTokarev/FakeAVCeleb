from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, HttpUrl
from typing import Literal, Optional
import aiofiles
import uuid
import os

from ..database import get_db
from ..models import Job, Result, AnonymousUser
from ..config import settings
from ..services.url_validator import validate_url, ValidationError
from ..services.queue import enqueue_job
from ..services.rate_limit import get_client_ip, allow_first_free, get_first_free_count, reset_first_free_count, _rate_limit_key

router = APIRouter()


class JobCreateBody(BaseModel):
    input_type: Literal["link", "upload"]
    input_url: Optional[HttpUrl] = None
    options: Optional[dict] = None


class JobCreateResponse(BaseModel):
    job_id: str
    status: str
    anonymous_id: Optional[str] = None  # set when server generated new ID for client to store


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: dict
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    result_id: Optional[str] = None


class MeResponse(BaseModel):
    anonymous_id: str
    total_completed: int
    paid_credits: int
    next_check_free: bool

def _parse_anonymous_id(x_anonymous_id: Optional[str]) -> tuple[str, bool]:
    """Return (anonymous_id, was_provided). If invalid or missing, generate new UUID."""
    if not x_anonymous_id or not x_anonymous_id.strip():
        return str(uuid.uuid4()), False
    try:
        uid = uuid.UUID(x_anonymous_id.strip())
        return str(uid), True
    except (ValueError, TypeError):
        return str(uuid.uuid4()), False


async def _get_or_create_anonymous_user(db: AsyncSession, anonymous_id: str) -> AnonymousUser:
    result = await db.execute(select(AnonymousUser).where(AnonymousUser.id == anonymous_id))
    user = result.scalar_one_or_none()
    if user:
        return user
    user = AnonymousUser(id=anonymous_id)
    db.add(user)
    await db.flush()
    return user


# 1st free, 2nd 1 EUR, 3rd free, 4th 1 EUR, ...
def _requires_payment(total_completed: int) -> bool:
    next_number = total_completed + 1
    return (next_number % 2) == 0


@router.get("/debug/rate-limit")
async def debug_rate_limit(request: Request):
    """Return current first-free count for this request's IP (for verifying rate limit)."""
    from ..config import settings
    ip = get_client_ip(request)
    key = _rate_limit_key(ip)
    count = await get_first_free_count(ip)
    return {
        "ip": ip,
        "key": key,
        "count": count,
        "limit": settings.max_first_free_per_ip_per_day,
    }


@router.post("/debug/rate-limit/reset")
async def debug_rate_limit_reset(request: Request):
    """Reset the first-free count for your IP (for testing). Call from same machine/browser as the app."""
    ip = get_client_ip(request)
    existed = await reset_first_free_count(ip)
    return {"ok": True, "message": "Rate limit counter reset for your IP.", "ip": ip, "had_count": existed}


@router.get("/me", response_model=MeResponse)
async def get_me(
    db: AsyncSession = Depends(get_db),
    x_anonymous_id: Optional[str] = Header(None, alias="X-Anonymous-Id"),
):
    anonymous_id, _ = _parse_anonymous_id(x_anonymous_id)
    user = await _get_or_create_anonymous_user(db, anonymous_id)
    return MeResponse(
        anonymous_id=anonymous_id,
        total_completed=user.total_completed,
        paid_credits=user.paid_credits,
        next_check_free=not _requires_payment(user.total_completed),
    )


@router.post("/jobs", response_model=JobCreateResponse)
async def create_job(
    request: Request,
    body: JobCreateBody,
    db: AsyncSession = Depends(get_db),
    x_anonymous_id: Optional[str] = Header(None, alias="X-Anonymous-Id"),
):
    if body.input_type == "link" and not body.input_url:
        raise HTTPException(status_code=400, detail="input_url required for link")
    if body.input_type == "upload":
        # Client must then call POST /jobs/{id}/upload
        pass

    anonymous_id, was_provided = _parse_anonymous_id(x_anonymous_id)
    user = await _get_or_create_anonymous_user(db, anonymous_id)

    # Rate limit: max N "first free" jobs per IP per day (reduces cookie-clear abuse)
    if user.total_completed == 0:
        ip = get_client_ip(request)
        if not await allow_first_free(ip):
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "RATE_LIMIT_FIRST_FREE",
                    "message": "Free check limit reached for this network. Try again tomorrow or pay 1 € for an analysis.",
                },
            )

    if _requires_payment(user.total_completed):
        if user.paid_credits <= 0:
            raise HTTPException(
                status_code=402,
                detail={
                    "code": "PAYMENT_REQUIRED",
                    "amount_eur": 1,
                    "message": "This check costs 1 €",
                },
            )
        user.paid_credits -= 1
        await db.flush()

    job = Job(
        status="CREATED",
        input_type=body.input_type,
        input_url=str(body.input_url) if body.input_url else None,
        options=body.options or {},
        anonymous_id=anonymous_id,
    )
    db.add(job)
    await db.flush()

    if body.input_type == "link":
        try:
            validate_url(str(body.input_url))
        except ValidationError as e:
            raise HTTPException(status_code=400, detail={"error_code": e.code, "message": str(e)})
        job.status = "FETCHING"
        await db.commit()
        await enqueue_job(job.id)
        return JobCreateResponse(
            job_id=job.id,
            status=job.status,
            anonymous_id=None if was_provided else anonymous_id,
        )

    await db.commit()
    return JobCreateResponse(
        job_id=job.id,
        status="CREATED",
        anonymous_id=None if was_provided else anonymous_id,
    )


@router.post("/jobs/{job_id}/upload", response_model=JobCreateResponse)
async def upload_video(
    job_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    if job.input_type != "upload":
        raise HTTPException(status_code=400, detail="Job is not an upload job")
    if job.status not in ("CREATED",):
        raise HTTPException(status_code=400, detail="Job already has file")

    ext = (file.filename or "").split(".")[-1].lower()
    if ext not in ("mp4", "mov", "webm"):
        raise HTTPException(status_code=400, detail={"error_code": "FORMAT_UNSUPPORTED"})

    size = 0
    chunk_size = 1024 * 1024
    job_dir = os.path.join(str(settings.storage_path), job_id)
    os.makedirs(job_dir, exist_ok=True)
    path = os.path.join(job_dir, f"upload.{ext}")

    try:
        async with aiofiles.open(path, "wb") as f:
            while chunk := await file.read(chunk_size):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(status_code=400, detail={"error_code": "TOO_LARGE"})
                await f.write(chunk)
    except HTTPException:
        if os.path.exists(path):
            os.remove(path)
        raise

    job.input_filename = f"upload.{ext}"
    job.artifacts = {"video_path": path}
    job.status = "UPLOADING"
    await db.commit()
    await enqueue_job(job_id)
    return JobCreateResponse(job_id=job_id, status="UPLOADING")


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")

    steps = ["FETCHING", "PREPROCESSING", "INFERENCING", "CLASSIFYING", "REPORTING", "DONE"]
    step = job.progress_step or job.status
    if step not in steps:
        step = job.status
    # UPLOADING = file received, show as step 1 so UI shows "Step 1 of N"
    if job.status == "UPLOADING":
        done = 1
        step = "FETCHING"  # display only; worker hasn't started yet
    else:
        done = steps.index(step) + 1 if step in steps else 0
    if job.status == "DONE":
        done = len(steps)
    total = len(steps)

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        progress={"step": step, "done": min(done, total), "total": total},
        error_code=job.error_code,
        error_message=job.error_message,
        result_id=job.result_id,
    )


@router.get("/jobs/{job_id}/result")
async def get_job_result(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    if job.status != "DONE" or not job.result_id:
        raise HTTPException(status_code=404, detail="Result not ready")

    r = await db.execute(select(Result).where(Result.id == job.result_id))
    res = r.scalar_one_or_none()
    if not res:
        raise HTTPException(status_code=404, detail="Result not found")

    return {
        "result": {
            "id": res.id,
            "job_id": res.job_id,
            "score_overall": float(res.score_overall),
            "confidence": res.confidence,
            "verdict": res.verdict or "uncertain",
            "sub_scores": res.sub_scores or {},
            "findings": res.findings or [],
            "flagged_frames": res.flagged_frames or [],
            "segments": res.segments or [],
            "signals": res.signals or {},
            "model_meta": res.model_meta or {},
        }
    }
