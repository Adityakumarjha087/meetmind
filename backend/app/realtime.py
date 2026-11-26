"""Socket.IO server: JWT-authenticated connections, per-meeting / per-workspace rooms."""

from __future__ import annotations

import asyncio
from typing import Any

import socketio

from app.core.config import get_settings
from app.core.errors import AuthError
from app.core.logging import get_logger
from app.core.security import decode_token
from app.db.session import session_scope
from app.models import Meeting, Membership

log = get_logger(__name__)


def build_socket_server() -> socketio.AsyncServer:
    settings = get_settings()
    manager = socketio.AsyncRedisManager(settings.redis_url) if settings.redis_url else None
    sio = socketio.AsyncServer(
        async_mode="asgi",
        cors_allowed_origins=settings.cors_origins,
        client_manager=manager,
        logger=False,
        engineio_logger=False,
    )
    register_handlers(sio)
    return sio


def _member_workspace(user_id: str, meeting_id: str | None, workspace_id: str | None) -> str | None:
    with session_scope() as db:
        if meeting_id:
            meeting = db.get(Meeting, meeting_id)
            if meeting is None:
                return None
            workspace_id = meeting.workspace_id
        if not workspace_id:
            return None
        membership = (
            db.query(Membership).filter_by(workspace_id=workspace_id, user_id=user_id).one_or_none()
        )
        return workspace_id if membership else None


def register_handlers(sio: socketio.AsyncServer) -> None:
    @sio.event
    async def connect(sid: str, environ: dict[str, Any], auth: dict[str, Any] | None = None) -> None:
        token = (auth or {}).get("token")
        if not token:
            raise socketio.exceptions.ConnectionRefusedError("authentication required")
        try:
            payload = decode_token(str(token), "access")
        except AuthError as exc:
            raise socketio.exceptions.ConnectionRefusedError("invalid token") from exc
        await sio.save_session(sid, {"user_id": payload["sub"]})

    @sio.event
    async def subscribe(sid: str, data: dict[str, Any]) -> dict[str, Any]:
        session = await sio.get_session(sid)
        meeting_id = data.get("meeting_id") if isinstance(data, dict) else None
        workspace_id = data.get("workspace_id") if isinstance(data, dict) else None
        ws = await asyncio.to_thread(_member_workspace, session["user_id"], meeting_id, workspace_id)
        if ws is None:
            return {"ok": False, "error": "forbidden"}
        room = f"meeting:{meeting_id}" if meeting_id else f"workspace:{ws}"
        await sio.enter_room(sid, room)
        return {"ok": True, "room": room}

    @sio.event
    async def unsubscribe(sid: str, data: dict[str, Any]) -> dict[str, Any]:
        room = data.get("room") if isinstance(data, dict) else None
        if room:
            await sio.leave_room(sid, str(room))
        return {"ok": True}
