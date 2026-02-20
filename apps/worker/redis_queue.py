import redis.asyncio as redis
from config import settings

QUEUE_NAME = "deepfake_jobs"


async def consume_queue(handler):
    r = redis.from_url(settings.redis_url)
    try:
        while True:
            result = await r.brpop(QUEUE_NAME, timeout=30)
            if result is None:
                break
            _, job_id = result
            job_id = job_id.decode() if isinstance(job_id, bytes) else job_id
            print(f"Processing job {job_id}", flush=True)
            await handler(job_id)
    finally:
        await r.aclose()
