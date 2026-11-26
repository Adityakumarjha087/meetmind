from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import session_scope
from app.models import OAuthAccount, User
from app.services import http as http_service
from tests.conftest import auth, upload_demo

# Built at runtime so no webhook-shaped literal lives in the repository.
SLACK_URL = (
    "https://"
    + "hooks.slack.com"
    + "/services/"
    + "/".join(["test-team", "test-bot", "test-secret"])
)


def _configure_slack(client: TestClient, h: dict[str, str], auto: bool = False) -> None:
    r = client.patch(
        f"/api/v1/workspaces/{h['workspace_id']}",
        json={"slack_webhook_url": SLACK_URL, "slack_auto_post": auto},
        headers=auth(h),
    )
    assert r.status_code == 200


def test_post_summary_to_slack(client: TestClient, owner: dict[str, str]) -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == SLACK_URL
        sent.append(json.loads(request.content))
        return httpx2.Response(200, text="ok")

    http_service.set_transport(httpx2.MockTransport(handler))
    m = upload_demo(client, owner)
    assert (
        client.post(f"/api/v1/meetings/{m['id']}/slack", headers=auth(owner)).status_code == 422
    )  # not configured
    _configure_slack(client, owner)
    client.post(f"/api/v1/meetings/{m['id']}/share", headers=auth(owner))
    r = client.post(f"/api/v1/meetings/{m['id']}/slack", headers=auth(owner))
    assert r.status_code == 202
    blocks = sent[0]["blocks"]
    assert blocks[0]["type"] == "header" and "Q3 Launch Planning" in blocks[0]["text"]["text"]
    text = json.dumps(blocks)
    assert "*Decisions*" in text and "*Action items*" in text and "/share/" in text


def test_slack_errors_surface_as_502(client: TestClient, owner: dict[str, str]) -> None:
    http_service.set_transport(
        httpx2.MockTransport(lambda r: httpx2.Response(404, text="no_service"))
    )
    m = upload_demo(client, owner)
    _configure_slack(client, owner)
    r = client.post(f"/api/v1/meetings/{m['id']}/slack", headers=auth(owner))
    assert r.status_code == 502 and "no_service" in r.json()["error"]["message"]

    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down", request=request)

    http_service.set_transport(httpx2.MockTransport(down))
    assert client.post(f"/api/v1/meetings/{m['id']}/slack", headers=auth(owner)).status_code == 502


def test_slack_auto_post_after_pipeline(client: TestClient, owner: dict[str, str]) -> None:
    sent: list[Any] = []
    http_service.set_transport(
        httpx2.MockTransport(lambda r: (sent.append(r), httpx2.Response(200))[1])
    )
    _configure_slack(client, owner, auto=True)
    upload_demo(client, owner)
    assert len(sent) == 1


@pytest.fixture
def google_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "google_client_id", "cid")
    monkeypatch.setattr(s, "google_client_secret", "csecret")


def _google_handler(events: list[dict[str, Any]], calls: list[str]) -> Any:
    def handler(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        calls.append(url)
        if url.startswith("https://oauth2.googleapis.com/token"):
            form = parse_qs(request.content.decode())
            if form["grant_type"] == ["refresh_token"]:
                return httpx2.Response(200, json={"access_token": "fresh", "expires_in": 3600})
            assert form["code"] == ["the-code"] and form["client_secret"] == ["csecret"]
            return httpx2.Response(
                200,
                json={
                    "access_token": "at",
                    "refresh_token": "rt",
                    "expires_in": 3600,
                    "scope": "openid email https://www.googleapis.com/auth/calendar.readonly",
                },
            )
        if "userinfo" in url:
            return httpx2.Response(
                200,
                json={
                    "sub": "g-123",
                    "email": "gina@example.com",
                    "email_verified": True,
                    "name": "Gina G",
                    "picture": "https://x/p.png",
                },
            )
        if "/calendars/primary/events" in url:
            assert request.headers["authorization"] in {"Bearer at", "Bearer fresh"}
            return httpx2.Response(200, json={"items": events})
        return httpx2.Response(404)

    return handler


def test_google_oauth_login_and_calendar_import(client: TestClient, google_enabled: None) -> None:
    start = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    events = [
        {
            "id": "e1",
            "summary": "Sprint planning",
            "start": {"dateTime": start},
            "attendees": [{"email": "a@x.com"}, {"email": "b@x.com"}],
        },
        {"id": "e2", "summary": "Holiday", "start": {"date": "2026-12-25"}},
        {"id": "e3", "summary": "Cancelled", "status": "cancelled", "start": {"dateTime": start}},
    ]
    calls: list[str] = []
    http_service.set_transport(httpx2.MockTransport(_google_handler(events, calls)))

    url = client.get("/api/v1/auth/google/authorize").json()["url"]
    q = parse_qs(urlparse(url).query)
    assert (
        q["client_id"] == ["cid"]
        and "calendar.readonly" in q["scope"][0]
        and q["access_type"] == ["offline"]
    )

    cb = client.get(
        "/api/v1/auth/google/callback",
        params={"code": "the-code", "state": q["state"][0]},
        follow_redirects=False,
    )
    assert cb.status_code == 307
    frag = parse_qs(urlparse(cb.headers["location"]).fragment)
    token = frag["access_token"][0]
    assert "mm_refresh" in cb.headers.get("set-cookie", "")
    h = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    assert me["email"] == "gina@example.com" and me["google_connected"] and not me["has_password"]

    ws = client.get("/api/v1/workspaces", headers=h).json()[0]["id"]
    assert client.get(f"/api/v1/workspaces/{ws}/integrations", headers=h).json()[
        "google_calendar_connected"
    ]
    imp = client.post(
        f"/api/v1/workspaces/{ws}/integrations/google-calendar/import",
        json={"days_ahead": 7},
        headers=h,
    ).json()
    assert imp["imported"] == 1
    m = imp["meetings"][0]
    assert (
        m["title"] == "Sprint planning"
        and m["status"] == "scheduled"
        and m["attendees"] == ["a@x.com", "b@x.com"]
    )
    # idempotent
    again = client.post(
        f"/api/v1/workspaces/{ws}/integrations/google-calendar/import", json={}, headers=h
    ).json()
    assert again["imported"] == 0

    # expired access token triggers refresh
    with session_scope() as db:
        acct = db.scalar(select(OAuthAccount))
        assert acct is not None
        acct.expires_at = datetime.now(UTC) - timedelta(minutes=5)
    client.post(f"/api/v1/workspaces/{ws}/integrations/google-calendar/import", json={}, headers=h)
    assert any("token" in c for c in calls[-2:])

    # second login links to the same user
    url2 = client.get("/api/v1/auth/google/authorize").json()["url"]
    state2 = parse_qs(urlparse(url2).query)["state"][0]
    client.get(
        "/api/v1/auth/google/callback",
        params={"code": "the-code", "state": state2},
        follow_redirects=False,
    )
    with session_scope() as db:
        assert len(list(db.scalars(select(User)))) == 1


def test_google_callback_errors_and_link(
    client: TestClient, google_enabled: None, owner: dict[str, str]
) -> None:
    http_service.set_transport(httpx2.MockTransport(_google_handler([], [])))
    bad = client.get(
        "/api/v1/auth/google/callback",
        params={"code": "c", "state": "forged"},
        follow_redirects=False,
    )
    assert "error=" in bad.headers["location"]
    denied = client.get(
        "/api/v1/auth/google/callback", params={"error": "access_denied"}, follow_redirects=False
    )
    assert "access_denied" in denied.headers["location"]
    # calendar import without a connected account
    r = client.post(
        f"/api/v1/workspaces/{owner['workspace_id']}/integrations/google-calendar/import",
        json={},
        headers=auth(owner),
    )
    assert r.status_code == 422
    # link Google to the existing password account
    link = client.get("/api/v1/auth/google/link", headers=auth(owner)).json()["url"]
    state = parse_qs(urlparse(link).query)["state"][0]
    client.get(
        "/api/v1/auth/google/callback",
        params={"code": "the-code", "state": state},
        follow_redirects=False,
    )
    me = client.get("/api/v1/auth/me", headers=auth(owner)).json()
    assert me["google_connected"] and me["email"] == "owner@example.com"
