import os
from functools import lru_cache

import redis
from django.conf import settings


@lru_cache(maxsize=1)
def get_celery_redis_client() -> redis.Redis:
    """
    Redis client dedicated for Celery-backed coordination (locks/trigger signals).

    IMPORTANT:
    - Uses CELERY_BROKER_URL (redis-celery) so we don't add load to redis-report
      which is meant for report caching and may be memory constrained/ephemeral.
    """
    broker_url = getattr(
        settings,
        "CELERY_BROKER_URL",
        os.environ.get("CELERY_BROKER_URL", "redis://redis-celery:6379/0"),
    )
    return redis.Redis.from_url(broker_url)


