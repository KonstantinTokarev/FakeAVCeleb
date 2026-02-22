from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, HttpUrl
from typing import Literal, Optional
import redis.asyncio as redis
import json
import uuid
import os

from ..database import get_db
from ..models import Job, Result
from ..config import settings
from ..services.url_validator import validate_url, ValidationError
from ..services.queue import enqueue_job

router = APIRouter()


class JobCreateBody(BaseModel):
    input_type: Literal["link", "upload"]
    input_url: Optional[HttpUrl] = None
    options: Optional[dict] = None


class JobCreateResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: dict
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    result_id: Optional[str] = None


@router.post("/jobs", response_model=JobCreateResponse)
async def create_job(body: JobCreateBody, db: AsyncSession = Depends(get_db)):
    if body.input_type == "link" and not body.input_url:
        raise HTTPException(status_code=400, detail="input_url required for link")
    if body.input_type == "upload":
        # Client must then call POST /jobs/{id}/upload
        pass

    job = Job(
        status="CREATED",
        input_type=body.input_type,
        input_url=str(body.input_url) if body.input_url else None,
        options=body.options or {},
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
        return JobCreateResponse(job_id=job.id, status=job.status)

    await db.commit()
    return JobCreateResponse(job_id=job.id, status="CREATED")


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
    job_dir = os.path.join(settings.storage_path, job_id)
    os.makedirs(job_dir, exist_ok=True)
    path = os.path.join(job_dir, f"upload.{ext}")

    with open(path, "wb") as f:
        while chunk := await file.read(chunk_size):
            size += len(chunk)
            if size > settings.max_upload_bytes:
                os.remove(path)
                raise HTTPException(status_code=400, detail={"error_code": "TOO_LARGE"})
            f.write(chunk)

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

    steps = ["FETCHING", "PREPROCESSING", "INFERENCING", "REPORTING", "DONE"]
    step = job.progress_step or job.status
    if step not in steps:
        step = job.status
    # UPLOADING = file received, show as step 1 so UI shows "Step 1 of 5"
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
