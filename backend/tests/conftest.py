from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="meetmind-tests-"))
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": f"sqlite+pysqlite:///{_TMP / 'test.db'}",
        "LOCAL_STORAGE_PATH": str(_TMP / "storage"),
        "STORAGE_BACKEND": "local",
        "TASK_ALWAYS_EAGER": "true",
        "RATE_LIMIT_ENABLED": "false",
        "LOG_JSON": "false",
        "LOG_LEVEL": "WARNING",
        "LLM_PROVIDER": "offline",
        "JWT_SECRET": "test-secret-test-secret-test-secret-123",
        "FFMPEG_BINARY": "ffmpeg-not-installed-for-tests",
    }
)
os.environ.pop("REDIS_URL", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402,F401
from app.db.base import Base  # noqa: E402
from app.db.session import get_engine, session_scope  # noqa: E402
from app.services import http as http_service  # noqa: E402

SEED_DIR = Path(__file__).resolve().parents[1] / "app" / "seed_data"
DEMO_WAV = SEED_DIR / "demo_meeting.wav"


@pytest.fixture(autouse=True)
def _fresh_db() -> Iterator[None]:
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    http_service.set_transport(None)


@pytest.fixture
def db():  # type: ignore[no-untyped-def]
    with session_scope() as session:
        yield session


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def register(
    client: TestClient, email: str = "owner@example.com", name: str = "Olivia Owner"
) -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/register", json={"email": email, "name": name, "password": "correct-horse-1"}
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    ws = client.get("/api/v1/workspaces", headers=headers).json()[0]["id"]
    return {"Authorization": headers["Authorization"], "workspace_id": ws}


@pytest.fixture
def owner(client: TestClient) -> dict[str, str]:
    return register(client)


def auth(h: dict[str, str]) -> dict[str, str]:
    return {"Authorization": h["Authorization"]}


def upload_demo(client: TestClient, h: dict[str, str], **form: str) -> dict:  # type: ignore[type-arg]
    with DEMO_WAV.open("rb") as fh:
        resp = client.post(
            f"/api/v1/workspaces/{h['workspace_id']}/meetings",
            headers=auth(h),
            files={"file": ("demo_meeting.wav", fh, "audio/wav")},
            data={"title": "Q3 Launch Planning", **form},
        )
    assert resp.status_code == 201, resp.text
    return resp.json()
