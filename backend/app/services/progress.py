import json
from typing import Any

from app.core.redis import get_sync_redis


def job_channel(job_id: str) -> str:
    return f"jobs:{job_id}:progress"


def publish_progress(job_id: str, payload: dict[str, Any]) -> None:
    message = {"job_id": job_id, **payload}
    redis = get_sync_redis()
    encoded = json.dumps(message, default=str)
    redis.setex(f"jobs:{job_id}:latest", 86400, encoded)
    redis.publish(job_channel(job_id), encoded)

