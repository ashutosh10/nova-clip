from celery import Celery

from app.core.config import settings

celery_app = Celery("nova_clip", broker=settings.redis_url, backend=settings.redis_url, include=["app.workers.tasks"])
celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    result_expires=86400,
    task_routes={
        "app.workers.tasks.generate_clip": {"queue": "gpu"},
        "app.workers.tasks.generate_sequence": {"queue": "gpu"},
        "app.workers.tasks.stitch_project": {"queue": "media"},
    },
)

