from ..config import settings
import redis.asyncio as redis

QUEUE_NAME = "deepfake_jobs"


async def enqueue_job(job_id: str) -> None:
    r = redis.from_url(settings.redis_url)
    try:
        await r.lpush(QUEUE_NAME, job_id)
    finally:
        await r.aclose()
