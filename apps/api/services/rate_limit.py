"""IP-based rate limiting for first-free job creation (per IP per day)."""
from datetime import datetime, timezone

from fastapi import Request

from ..config import settings
import redis.asyncio as redis

KEY_PREFIX = "first_free_per_ip"
TTL_SECONDS = 86400 * 2  # 2 days so key expires after the "day" window


def get_client_ip(request: Request) -> str:
    """Client IP: X-Forwarded-For (first hop) or request.client.host. Normalized so IPv6 localhost = IPv4."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    elif request.client:
        ip = request.client.host
    else:
        return "unknown"
    # Normalize so ::1 and 127.0.0.1 count as same for rate limiting
    if ip == "::1":
        return "127.0.0.1"
    return ip


def _rate_limit_key(ip: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{KEY_PREFIX}:{ip}:{today}"


async def get_first_free_count(ip: str) -> int:
    """Current first-free count for this IP today (for debugging)."""
    key = _rate_limit_key(ip)
    r = redis.from_url(settings.redis_url)
    try:
        val = await r.get(key)
        return int(val) if val else 0
    finally:
        await r.aclose()


async def reset_first_free_count(ip: str) -> bool:
    """Delete the rate-limit key for this IP today (for testing). Returns True if key existed."""
    key = _rate_limit_key(ip)
    r = redis.from_url(settings.redis_url)
    try:
        n = await r.delete(key)
        return n > 0
    finally:
        await r.aclose()


async def allow_first_free(ip: str) -> bool:
    """
    Check and consume one "first free" slot for this IP for today.
    Returns True if allowed (counter incremented), False if limit exceeded.
    Uses INCR then check; if over limit we DECR to undo (avoids race).
    """
    key = _rate_limit_key(ip)
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
