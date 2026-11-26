from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.core.security import create_token
from tests.conftest import register


def test_register_login_me(client: TestClient) -> None:
    h = register(client, "a@example.com", "Ada Lovelace")
    me = client.get("/api/v1/auth/me", headers={"Authorization": h["Authorization"]})
    assert me.status_code == 200
    assert me.json()["email"] == "a@example.com"
    assert me.json()["has_password"] is True

    ok = client.post(
        "/api/v1/auth/login", json={"email": "A@example.com", "password": "correct-horse-1"}
    )
    assert ok.status_code == 200
    assert ok.json()["token_type"] == "bearer"
    assert "mm_refresh" in ok.cookies

    ws = client.get("/api/v1/workspaces", headers={"Authorization": h["Authorization"]}).json()
    assert ws[0]["role"] == "owner" and ws[0]["name"] == "Ada's workspace"


def test_register_duplicate_and_validation(client: TestClient) -> None:
    register(client, "dup@example.com")
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "dup@example.com", "name": "X", "password": "longenough"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"
    bad = client.post(
        "/api/v1/auth/register", json={"email": "not-an-email", "name": "X", "password": "short"}
    )
    assert bad.status_code == 422
    body = bad.json()["error"]
    assert body["code"] == "validation_error" and len(body["details"]) == 2


def test_login_failures(client: TestClient) -> None:
    register(client, "b@example.com")
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "b@example.com", "password": "wrong"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong"}
        ).status_code
        == 401
    )


def test_protected_requires_valid_access_token(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"}).status_code
        == 401
    )
    refresh, _, _ = create_token("u", "refresh", timedelta(minutes=5))
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh}"})
    assert resp.status_code == 401 and resp.json()["error"]["message"] == "Wrong token type"
    expired, _, _ = create_token("u", "access", timedelta(seconds=-5))
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}).json()[
            "error"
        ]["message"]
        == "Token expired"
    )


def test_refresh_rotation_and_reuse_detection(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "r@example.com", "name": "R", "password": "correct-horse-1"},
    )
    first = resp.json()["refresh_token"]
    # body-based refresh (API clients)
    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert r1.status_code == 200
    second = r1.json()["refresh_token"]
    assert second != first
    # cookie-based refresh (browser)
    client.cookies.set("mm_refresh", second, path="/api/v1/auth")
    r2 = client.post("/api/v1/auth/refresh")
    assert r2.status_code == 200
    third = r2.json()["refresh_token"]
    client.cookies.clear()
    # reusing a rotated token revokes the whole family
    reuse = client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert reuse.status_code == 401 and "reuse" in reuse.json()["error"]["message"]
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": third}).status_code == 401


def test_logout_revokes_refresh(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "l@example.com", "name": "L", "password": "correct-horse-1"},
    )
    token = resp.json()["refresh_token"]
    assert client.post("/api/v1/auth/logout", json={"refresh_token": token}).status_code == 204
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": token}).status_code == 401
    client.cookies.clear()
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_google_disabled_returns_503(client: TestClient) -> None:
    resp = client.get("/api/v1/auth/google/authorize")
    assert resp.status_code == 503
    cb = client.get("/api/v1/auth/google/callback", follow_redirects=False)
    assert cb.status_code == 307 and "error=missing_code" in cb.headers["location"]
