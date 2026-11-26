"""Pipeline progress fan-out to Socket.IO rooms (cross-process via Redis when available)."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any, Protocol

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)
PROGRESS_EVENT = "meeting:progress"


class Emitter(Protocol):
    def emit(self, event: str, data: dict[str, Any], rooms: list[str]) -> None: ...


class NullEmitter:
    def emit(self, event: str, data: dict[str, Any], rooms: list[str]) -> None:
        return None


class RedisEmitter:
    """Write-only Socket.IO manager: workers publish, API replicas deliver to connected clients."""

    def __init__(self, url: str) -> None:
        import socketio

        self._mgr = socketio.RedisManager(url, write_only=True)

    def emit(self, event: str, data: dict[str, Any], rooms: list[str]) -> None:
        for room in rooms:
            try:
                self._mgr.emit(event, data, room=room, namespace="/")
            except Exception:  # progress is best-effort; never fail the pipeline over it
                log.warning("progress_emit_failed", room=room)


class LoopEmitter:
    """Same-process emitter used when the pipeline runs inline inside the API (no Redis)."""

    def __init__(self, server: Any, loop: asyncio.AbstractEventLoop) -> None:
        self._server = server
        self._loop = loop

    def emit(self, event: str, data: dict[str, Any], rooms: list[str]) -> None:
        for room in rooms:
            if self._loop.is_running():
                asyncio.run_coroutine_threadsafe(self._server.emit(event, data, room=room), self._loop)


_override: Emitter | None = None


def set_emitter(emitter: Emitter | None) -> None:
    global _override
    _override = emitter


@lru_cache
def _default_emitter() -> Emitter:
    url = get_settings().redis_url
    return RedisEmitter(url) if url else NullEmitter()


def get_emitter() -> Emitter:
    return _override or _default_emitter()
