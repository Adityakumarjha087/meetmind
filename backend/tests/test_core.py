from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import boto3
import pytest
import socketio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from moto import mock_aws
from sqlalchemy import select

from app.core.config import DEV_JWT_SECRET, Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.ratelimit import MemoryCounterStore, RateLimitMiddleware, RateRule
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import session_scope
from app.embeddings.factory import build_embedder
from app.intelligence.factory import build_chat_model, build_engine
from app.intelligence.heuristic import HeuristicEngine
from app.models import Meeting, User
from app.realtime import build_socket_server
from app.services import dispatch, progress
from app.services.storage import LocalStorage, S3Storage, StorageError
from app.stt.factory import build_diarizer, build_transcriber
from tests.conftest import auth, register, upload_demo


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["checks"]["database"] == "ok" and body["checks"]["storage"] == "ok"
    assert body["backends"]["llm"] == "offline"
    assert client.get("/health/live").json() == {"status": "ok"}
    assert r.headers["x-request-id"]


def test_openapi_documents_all_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for p in [
        "/api/v1/auth/login",
        "/api/v1/workspaces/{workspace_id}/meetings",
        "/api/v1/workspaces/{workspace_id}/ask",
        "/api/v1/meetings/{meeting_id}/export",
        "/api/v1/action-items/{item_id}",
        "/api/v1/share/{token}",
    ]:
        assert p in paths
    assert client.get("/docs").status_code == 200


def test_rate_limit_middleware() -> None:
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        store=MemoryCounterStore(),
        rules=[RateRule("/login", 2)],
        default_limit=5,
    )

    @app.get("/login")
    def login() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    c = TestClient(app)
    assert c.get("/login").headers["x-ratelimit-remaining"] == "1"
    c.get("/login")
    blocked = c.get("/login")
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "60"
    assert all(c.get("/health").status_code == 200 for _ in range(10))  # exempt


def test_rate_limit_falls_back_when_store_fails() -> None:
    class Broken:
        def hit(self, key: str, window_s: int) -> int:
            raise ConnectionError("redis down")

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, store=Broken(), rules=[], default_limit=1)

    @app.get("/x")
    def x() -> dict[str, bool]:
        return {"ok": True}

    c = TestClient(app)
    assert c.get("/x").status_code == 200
    assert c.get("/x").status_code == 429


def test_memory_store_window_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.ratelimit as rl

    store = MemoryCounterStore()
    now = [100.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: now[0])
    assert store.hit("k", 60) == 1 and store.hit("k", 60) == 2
    now[0] += 61
    assert store.hit("k", 60) == 1


def test_unhandled_errors_are_wrapped() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internals")

    r = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error" and "secret" not in r.text
    assert TestClient(app).get("/missing").json()["error"]["code"] == "http_error"


def test_password_hashing() -> None:
    h = hash_password("s3cret-pass")
    assert verify_password("s3cret-pass", h) and not verify_password("nope", h)
    assert not verify_password("x", None) and not verify_password("x", "not-a-hash")


def test_settings_guards() -> None:
    with pytest.raises(ValueError, match="production"):
        Settings(environment="production", jwt_secret=DEV_JWT_SECRET)
    with pytest.raises(ValueError, match="32 characters"):
        Settings(jwt_secret="short")
    s = Settings(cors_origins="http://a.com, http://b.com", jwt_secret="x" * 40)  # type: ignore[arg-type]
    assert s.cors_origins == ["http://a.com", "http://b.com"] and not s.google_enabled


def test_local_storage(tmp_path: Path) -> None:
    st = LocalStorage(tmp_path / "s")
    st.put_bytes("w/m/a.txt", b"hello world")
    assert st.get_bytes("w/m/a.txt") == b"hello world" and st.size("w/m/a.txt") == 11
    assert st.get_range("w/m/a.txt", 6, 10) == b"world"
    st.download("w/m/a.txt", tmp_path / "d.txt")
    st.delete_prefix("w/m")
    with pytest.raises(StorageError):
        st.get_bytes("w/m/a.txt")
    with pytest.raises(StorageError):
        st.put_bytes("../escape", b"x")
    with pytest.raises(StorageError):
        st.size("nope")
    assert st.healthy()


@mock_aws
def test_s3_storage(tmp_path: Path) -> None:
    s = get_settings().model_copy(update={"s3_bucket": "meetmind-test", "s3_region": "us-east-1"})
    client = boto3.client("s3", region_name="us-east-1")
    st = S3Storage(s, client=client)
    assert not st.healthy()
    st.ensure_bucket()
    assert st.healthy()
    src = tmp_path / "f.bin"
    src.write_bytes(b"0123456789")
    st.put_file("w/m/f.bin", src, "application/octet-stream")
    st.put_bytes("w/m/g.txt", b"abc")
    assert st.size("w/m/f.bin") == 10 and st.get_range("w/m/f.bin", 2, 4) == b"234"
    assert st.download("w/m/g.txt", tmp_path / "g.txt").read_bytes() == b"abc"
    st.delete_prefix("w/m")
    with pytest.raises(StorageError):
        st.get_bytes("w/m/g.txt")
    with pytest.raises(StorageError):
        st.size("w/m/f.bin")
    with pytest.raises(StorageError):
        st.download("w/m/f.bin", tmp_path / "x")


def test_backend_factories(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    assert isinstance(build_engine(s), HeuristicEngine)
    assert build_transcriber(s).name == "sidecar" and build_diarizer(s).name == "spectral"
    assert build_embedder(s).name == "hashing"
    for provider in ("anthropic", "openai", "gemini"):
        with pytest.raises(RuntimeError, match="requires"):
            build_chat_model(s.model_copy(update={"llm_provider": provider}))
    keyed = s.model_copy(
        update={"anthropic_api_key": "k", "openai_api_key": "k", "gemini_api_key": "k"}
    )
    assert (
        build_engine(keyed.model_copy(update={"llm_provider": "anthropic"})).name
        == "anthropic:claude-opus-5-5"
    )
    assert (
        build_engine(keyed.model_copy(update={"llm_provider": "openai"})).name
        == "openai:gpt-4o-mini"
    )
    assert build_engine(keyed.model_copy(update={"llm_provider": "gemini"})).name.startswith(
        "gemini:"
    )
    assert (
        build_engine(keyed.model_copy(update={"llm_provider": "ollama", "llm_model": "qwen"})).name
        == "ollama:qwen"
    )
    assert build_embedder(keyed.model_copy(update={"embedding_backend": "openai"})).name == "openai"
    assert (
        build_transcriber(keyed.model_copy(update={"stt_backend": "openai_whisper"})).name
        == "openai_whisper"
    )
    with pytest.raises(RuntimeError):
        build_transcriber(s.model_copy(update={"stt_backend": "openai_whisper"}))
    with pytest.raises(RuntimeError):
        build_embedder(s.model_copy(update={"embedding_backend": "openai"}))


def test_openai_embedder_batches() -> None:
    from app.embeddings.openai_embedder import OpenAIEmbedder

    calls: list[int] = []

    class Emb:
        def create(self, model: str, input: list[str], dimensions: int) -> Any:
            calls.append(len(input))
            return SimpleNamespace(
                data=[SimpleNamespace(embedding=[0.1] * dimensions) for _ in input]
            )

    e = OpenAIEmbedder(SimpleNamespace(embeddings=Emb()), dim=8)
    assert len(e.embed(["x"] * 300)) == 300 and calls == [256, 44] and e.embed([]) == []


def test_dispatch_uses_celery_when_redis_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import worker

    s = get_settings()
    monkeypatch.setattr(s, "task_always_eager", False)
    monkeypatch.setattr(s, "redis_url", "redis://localhost:1/0")
    sent: list[str] = []
    monkeypatch.setattr(worker.process_meeting, "delay", sent.append)
    assert dispatch.enqueue_pipeline("m1", SimpleNamespace(add_task=lambda *a: None)) == "celery"  # type: ignore[arg-type]
    assert sent == ["m1"]


def test_worker_task_runs_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import worker
    from app.services import pipeline

    ran: list[str] = []
    monkeypatch.setattr(pipeline, "run_pipeline", ran.append)
    assert worker.process_meeting.run("abc") == "abc" and ran == ["abc"]


def test_progress_emitters(monkeypatch: pytest.MonkeyPatch) -> None:
    progress.NullEmitter().emit("e", {}, ["r"])

    emitted: list[tuple[str, str]] = []

    class FakeServer:
        async def emit(self, event: str, data: dict[str, Any], room: str) -> None:
            emitted.append((event, room))

    async def run() -> None:
        loop = asyncio.get_running_loop()
        em = progress.LoopEmitter(FakeServer(), loop)
        await asyncio.to_thread(em.emit, "meeting:progress", {"a": 1}, ["meeting:1", "workspace:2"])
        await asyncio.sleep(0.05)

    asyncio.run(run())
    assert emitted == [("meeting:progress", "meeting:1"), ("meeting:progress", "workspace:2")]

    class FakeMgr:
        def __init__(self, url: str, write_only: bool) -> None:
            self.calls: list[str] = []

        def emit(self, event: str, data: Any, room: str, namespace: str) -> None:
            if room == "bad":
                raise ConnectionError
            self.calls.append(room)

    monkeypatch.setattr(socketio, "RedisManager", FakeMgr)
    red = progress.RedisEmitter("redis://x")
    red.emit("e", {}, ["ok", "bad"])
    assert red._mgr.calls == ["ok"]  # type: ignore[attr-defined]
    progress.set_emitter(progress.NullEmitter())
    assert isinstance(progress.get_emitter(), progress.NullEmitter)
    progress.set_emitter(None)


def test_socketio_auth_and_rooms(client: TestClient, owner: dict[str, str]) -> None:
    m = upload_demo(client, owner)
    stranger = register(client, "s@example.com", "Stranger")
    sio = build_socket_server()
    handlers = sio.handlers["/"]
    with session_scope() as db:
        owner_id = db.scalar(select(User.id).where(User.email == "owner@example.com"))
        stranger_id = db.scalar(select(User.id).where(User.email == "s@example.com"))
    assert owner_id and stranger_id and stranger

    sessions: dict[str, dict[str, Any]] = {}
    rooms: list[str] = []

    async def save_session(sid: str, data: dict[str, Any]) -> None:
        sessions[sid] = data

    async def get_session(sid: str) -> dict[str, Any]:
        return sessions[sid]

    async def enter_room(sid: str, room: str) -> None:
        rooms.append(room)

    async def leave_room(sid: str, room: str) -> None:
        rooms.remove(room)

    sio.save_session, sio.get_session, sio.enter_room, sio.leave_room = (
        save_session,
        get_session,
        enter_room,
        leave_room,
    )  # type: ignore[method-assign]

    async def flow() -> None:
        with pytest.raises(socketio.exceptions.ConnectionRefusedError):
            await handlers["connect"]("x", {}, None)
        with pytest.raises(socketio.exceptions.ConnectionRefusedError):
            await handlers["connect"]("x", {}, {"token": "bad"})
        await handlers["connect"]("own", {}, {"token": create_access_token(owner_id)})
        await handlers["connect"]("str", {}, {"token": create_access_token(stranger_id)})
        assert (await handlers["subscribe"]("own", {"meeting_id": m["id"]}))["ok"]
        assert (await handlers["subscribe"]("own", {"workspace_id": owner["workspace_id"]}))[
            "room"
        ] == f"workspace:{owner['workspace_id']}"
        assert not (await handlers["subscribe"]("str", {"meeting_id": m["id"]}))["ok"]
        assert not (await handlers["subscribe"]("own", {"meeting_id": "missing"}))["ok"]
        assert not (await handlers["subscribe"]("own", {}))["ok"]
        await handlers["unsubscribe"]("own", {"room": f"meeting:{m['id']}"})

    asyncio.run(flow())
    assert rooms == [f"workspace:{owner['workspace_id']}"]


def test_seed_is_idempotent() -> None:
    from app.seed import seed

    assert seed() is True
    assert seed() is False
    with session_scope() as db:
        meetings = {m.title: m for m in db.scalars(select(Meeting))}
        assert set(meetings) == {
            "Q3 Launch Planning",
            "Weekly Engineering Sync",
            "Customer Feedback Review",
            "Design Review: Onboarding v2",
        }
        assert all(
            m.status.value == "completed"
            for t, m in meetings.items()
            if t != "Design Review: Onboarding v2"
        )
        assert [s.display_name for s in meetings["Q3 Launch Planning"].speakers] == [
            "Priya",
            "Marcus",
            "Raj",
        ]
        assert sorted(s.display_name for s in meetings["Weekly Engineering Sync"].speakers) == [
            "Dana",
            "Leo",
            "Mia",
        ]
        q3_summary = (meetings["Q3 Launch Planning"].insights or {})["executive_summary"]
        assert "Speaker " not in q3_summary
        assert "assigned to Marcus, Raj." in q3_summary  # regenerated, not duplicated


def test_pipeline_handles_missing_meeting_and_audio(
    client: TestClient, owner: dict[str, str]
) -> None:
    from app.services.pipeline import run_pipeline

    run_pipeline("does-not-exist")
    with session_scope() as db:
        meeting = Meeting(workspace_id=owner["workspace_id"], title="No audio")
        db.add(meeting)
        db.flush()
        mid = meeting.id
    run_pipeline(mid)
    detail = client.get(f"/api/v1/meetings/{mid}", headers=auth(owner)).json()
    assert detail["status"] == "failed" and "No audio" in detail["error"]


def test_list_settings_parse_csv_and_json_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://a.com, http://b.com")
    monkeypatch.setenv("SLACK_ALLOWED_HOSTS", '["hooks.example.com"]')
    s = Settings()
    assert s.cors_origins == ["http://a.com", "http://b.com"]
    assert s.slack_allowed_hosts == ["hooks.example.com"]
