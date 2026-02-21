import time

import redis.asyncio as aioredis
from fastapi import HTTPException, Request

from app.config import settings


async def check_rate_limit(request: Request, group_id: str) -> None:
    """Sliding-window rate limiter keyed per group_id, backed by Redis sorted sets.

    Skips rate limiting gracefully if Redis is not available on request.app.state
    (e.g. during unit tests that don't set up Redis).
    """
    redis_client: aioredis.Redis | None = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return

    key = f"rate:{group_id}"
    now = time.time()
    window_start = now - settings.RATE_LIMIT_WINDOW_SECONDS

    async with redis_client.pipeline(transaction=True) as pipe:
        pipe.zremrangebyscore(key, 0, window_start)      # Remove expired entries
        pipe.zadd(key, {str(now): now})                   # Add current request timestamp
        pipe.zcard(key)                                    # Count requests in window
        pipe.expire(key, settings.RATE_LIMIT_WINDOW_SECONDS + 1)
        results = await pipe.execute()

    count = results[2]
    if count > settings.RATE_LIMIT_MAX_MESSAGES:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
