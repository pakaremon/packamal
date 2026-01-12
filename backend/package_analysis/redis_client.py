import os
from functools import lru_cache

import redis
from django.conf import settings


@lru_cache(maxsize=1)
def get_redis_client():
    """
    Return a singleton Redis client for report caching.
    Uses REDIS_CACHE_URL from settings or environment variable.
    This Redis instance is separate from Celery's Redis (redis-celery).
    """
    redis_url = getattr(
        settings,
        "REDIS_CACHE_URL",
        os.environ.get("REDIS_CACHE_URL", "redis://redis:6379/0"),
    )
    return redis.Redis.from_url(redis_url)


