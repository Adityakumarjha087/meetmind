"""ASGI entrypoint: FastAPI app wrapped by the Socket.IO server."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    action_items,
    ask,
    auth,
    health,
    integrations,
    meetings,
    public,
    workspaces,
)
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.core.ratelimit import MemoryCounterStore, RateLimitMiddleware, RateRule, RedisCounterStore
from app.realtime import build_socket_server
from app.services.progress import LoopEmitter, set_emitter

log = get_logger(__name__)

DESCRIPTION = """
MeetMind ingests meeting recordings, transcribes them with speaker labels and turns them into
summaries, decisions and action items. Authenticate with `POST /api/v1/auth/login` and send the
access token as `Authorization: Bearer <token>`. Live pipeline progress is pushed over Socket.IO
(`meeting:progress` events) at `/socket.io`.
"""


def create_app(sio: socketio.AsyncServer | None = None) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if sio is not None and not settings.redis_url:
            set_emitter(LoopEmitter(sio, asyncio.get_running_loop()))
        if settings.task_always_eager or not settings.redis_url:
            # No separate worker in this mode: the API process owns crash recovery.
            from app.services.dispatch import recover_and_requeue

            try:
                recover_and_requeue()
            except Exception:  # never block startup (e.g. tables not migrated yet)
                log.warning("startup_recovery_skipped")
        log.info(
            "startup",
            environment=settings.environment,
            llm=settings.llm_provider,
            stt=settings.stt_backend,
        )
        yield
        set_emitter(None)

    app = FastAPI(
        title="MeetMind API",
        version="0.1.0",
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    register_exception_handlers(app)

    if settings.rate_limit_enabled:
        store = (
            RedisCounterStore(settings.redis_url) if settings.redis_url else MemoryCounterStore()
        )
        p = settings.api_prefix
        app.add_middleware(
            RateLimitMiddleware,
            store=store,
            rules=[
                RateRule(f"{p}/auth/login", settings.rate_limit_auth_per_minute),
                RateRule(f"{p}/auth/register", settings.rate_limit_auth_per_minute),
                RateRule(f"{p}/auth/refresh", settings.rate_limit_auth_per_minute * 3),
                RateRule(
                    f"{p}/workspaces/", settings.rate_limit_upload_per_minute, frozenset({"POST"})
                ),
            ],
            default_limit=settings.rate_limit_default_per_minute,
            trust_proxy_headers=settings.trust_proxy_headers,
        )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Content-Disposition", "X-RateLimit-Remaining"],
    )

    app.include_router(health.router)
    for router in (auth, workspaces, meetings, action_items, ask, public, integrations):
        app.include_router(router.router, prefix=settings.api_prefix)
    return app


def create_asgi() -> socketio.ASGIApp:
    sio = build_socket_server()
    return socketio.ASGIApp(sio, other_asgi_app=create_app(sio), socketio_path="socket.io")


app = create_asgi()
