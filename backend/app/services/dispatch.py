"""Hand a meeting to the background pipeline (Celery in deployment, in-process when eager)."""

from __future__ import annotations

from fastapi import BackgroundTasks

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


def enqueue_pipeline(meeting_id: str, background: BackgroundTasks) -> str:
    if get_settings().task_always_eager or not get_settings().redis_url:
        from app.services.pipeline import run_pipeline

        background.add_task(run_pipeline, meeting_id)
        return "inline"
    from app.worker import process_meeting

    process_meeting.delay(meeting_id)
    log.info("pipeline_enqueued", meeting_id=meeting_id)
    return "celery"
