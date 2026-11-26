"""Celery application and tasks (run with: celery -A app.worker worker)."""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level, settings.log_json)

celery_app = Celery(
    "meetmind",
    broker=settings.redis_url or "memory://",
    backend=settings.redis_url or "cache+memory://",
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    task_time_limit=4 * 3600,
    broker_connection_retry_on_startup=True,
    task_always_eager=settings.task_always_eager,
)


@celery_app.task(name="meetmind.process_meeting")
def process_meeting(meeting_id: str) -> str:
    from app.services.pipeline import run_pipeline

    run_pipeline(meeting_id)
    return meeting_id
