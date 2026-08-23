from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from app.core.config import settings


def get_sync_redis() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def get_async_redis() -> AsyncRedis:
    return AsyncRedis.from_url(settings.redis_url, decode_responses=True)

