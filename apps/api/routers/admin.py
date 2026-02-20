from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from ..database import get_db
from ..models import Job

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/jobs")
async def list_jobs(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Job)
        .order_by(desc(Job.created_at))
        .limit(limit)
    )
    jobs = result.scalars().all()
    return {
        "jobs": [
            {
                "id": j.id,
                "status": j.status,
                "input_type": j.input_type,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "error_code": j.error_code,
                "error_message": j.error_message,
                "result_id": j.result_id,
            }
            for j in jobs
        ]
    }
