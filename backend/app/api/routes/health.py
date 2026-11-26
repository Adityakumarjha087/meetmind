from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_engine
from app.services.audio import ffmpeg_available
from app.services.storage import get_storage

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health")
def health() -> JSONResponse:
    settings = get_settings()
    checks: dict[str, Any] = {}
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc.__class__.__name__}"
    if settings.redis_url:
        try:
            import redis

            redis.Redis.from_url(settings.redis_url, socket_timeout=1).ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error: {exc.__class__.__name__}"
    try:
        checks["storage"] = "ok" if get_storage().healthy() else "error"
    except Exception as exc:
        checks["storage"] = f"error: {exc.__class__.__name__}"
    checks["ffmpeg"] = "ok" if ffmpeg_available() else "missing (WAV-only fallback)"
    healthy = all(v == "ok" for k, v in checks.items() if k != "ffmpeg")
    return JSONResponse(
        {
            "status": "ok" if healthy else "degraded",
            "checks": checks,
            "version": "0.1.0",
            "backends": {
                "llm": settings.llm_provider,
                "stt": settings.stt_backend,
                "diarizer": settings.diarizer_backend,
                "embeddings": settings.embedding_backend,
                "storage": settings.storage_backend,
            },
        },
        status_code=200 if healthy else 503,
    )
