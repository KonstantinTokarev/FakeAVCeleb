"""IP-based rate limiting for first-free job creation (per IP per day)."""
from datetime import datetime, timezone

from fastapi import Request

from ..config import settings
import redis.asyncio as redis

KEY_PREFIX = "first_free_per_ip"
TTL_SECONDS = 86400 * 2  # 2 days so key expires after the "day" window


def get_client_ip(request: Request) -> str:
    """Client IP: X-Forwarded-For (first hop) or request.client.host."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


async def allow_first_free(ip: str) -> bool:
    """
    Check and consume one "first free" slot for this IP for today.
    Returns True if allowed (counter incremented), False if limit exceeded.
    Uses INCR then check; if over limit we DECR to undo (avoids race).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"{KEY_PREFIX}:{ip}:{today}"
    limit = settings.max_first_free_per_ip_per_day

    r = redis.from_url(settings.redis_url)
    try:
        count = await r.incr(key)
        await r.expire(key, TTL_SECONDS)
        if count > limit:
            await r.decr(key)  # undo so we don't count rejected requests
            return False
        return True
    finally:
        await r.aclose()
