"""Google OAuth 2.0 (sign-in + Calendar scope) and Google Calendar meeting import."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx2
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AuthError, IntegrationError, ServiceUnavailable, ValidationFailed
from app.core.security import create_token, decode_token
from app.models import Meeting, MeetingSource, MeetingStatus, OAuthAccount, User
from app.services import http

SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/calendar.readonly",
]


def _require_enabled() -> None:
    if not get_settings().google_enabled:
        raise ServiceUnavailable("Google OAuth is not configured (set GOOGLE_CLIENT_ID/SECRET)")


def authorization_url(link_user_id: str | None = None) -> str:
    """Build the consent URL. ``state`` is a signed, short-lived JWT (CSRF protection)."""
    _require_enabled()
    settings = get_settings()
    state, _, _ = create_token(
        link_user_id or "anonymous",
        "oauth_state",
        timedelta(minutes=10),
        {"link": bool(link_user_id)},
    )
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return f"{settings.google_auth_base}/o/oauth2/v2/auth?{urlencode(params)}"


def _token_request(data: dict[str, str]) -> dict[str, Any]:
    settings = get_settings()
    body = {
        "client_id": settings.google_client_id or "",
        "client_secret": settings.google_client_secret or "",
        **data,
    }
    try:
        with http.client() as c:
            resp = c.post(settings.google_token_url, data=body)
    except httpx2.HTTPError as exc:
        raise IntegrationError("Could not reach Google") from exc
    if resp.status_code != 200:
        raise AuthError("Google token exchange failed")
    result: dict[str, Any] = resp.json()
    return result


def exchange_code(db: Session, code: str, state: str) -> User:
    """Complete the OAuth flow: verify state, exchange code, upsert the user and store tokens."""
    _require_enabled()
    claims = decode_token(state, "oauth_state")
    tokens = _token_request(
        {
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": get_settings().google_redirect_uri,
        }
    )
    try:
        with http.client() as c:
            resp = c.get(
                get_settings().google_userinfo_url,
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
    except httpx2.HTTPError as exc:
        raise IntegrationError("Could not reach Google") from exc
    if resp.status_code != 200:
        raise AuthError("Could not fetch Google profile")
    profile = resp.json()
    sub, email = str(profile["sub"]), str(profile.get("email", "")).lower()
    if not email or not profile.get("email_verified", False):
        raise AuthError("Google account email is not verified")

    from app.services.accounts import create_user_with_workspace

    user: User | None
    if claims.get("link"):
        user = db.get(User, claims["sub"])
        if user is None:
            raise AuthError("Unknown user for account linking")
    else:
        user = db.scalar(select(User).where(User.google_sub == sub)) or db.scalar(
            select(User).where(User.email == email)
        )
        if user is None:
            user = create_user_with_workspace(
                db, email=email, name=profile.get("name") or email, password=None
            )
    user.google_sub = sub
    user.avatar_url = profile.get("picture") or user.avatar_url

    account = db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.user_id == user.id, OAuthAccount.provider == "google"
        )
    ) or OAuthAccount(user_id=user.id, provider="google", subject=sub)
    account.access_token = tokens.get("access_token")
    account.refresh_token = tokens.get("refresh_token") or account.refresh_token
    account.expires_at = datetime.now(UTC) + timedelta(seconds=int(tokens.get("expires_in", 3600)))
    account.scopes = tokens.get("scope")
    db.add(account)
    db.flush()
    return user


def _valid_access_token(db: Session, account: OAuthAccount) -> str:
    expires = account.expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if account.access_token and expires and expires > datetime.now(UTC) + timedelta(seconds=60):
        return account.access_token
    if not account.refresh_token:
        raise ValidationFailed("Google session expired - reconnect Google Calendar")
    try:
        tokens = _token_request({"refresh_token": account.refresh_token, "grant_type": "refresh_token"})
    except AuthError as exc:  # revoked/expired grant: the user must re-consent, not re-login
        raise ValidationFailed("Google session expired - reconnect Google Calendar") from exc
    account.access_token = tokens["access_token"]
    account.expires_at = datetime.now(UTC) + timedelta(seconds=int(tokens.get("expires_in", 3600)))
    db.flush()
    return account.access_token


def import_calendar_events(
    db: Session, user: User, workspace_id: str, days_ahead: int = 14
) -> list[Meeting]:
    """Create 'scheduled' meetings for upcoming events that have at least one other attendee."""
    account = db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.user_id == user.id, OAuthAccount.provider == "google"
        )
    )
    if account is None:
        raise ValidationFailed("Connect Google Calendar first")
    if "calendar" not in (account.scopes or ""):
        raise ValidationFailed("Calendar permission was not granted")
    token = _valid_access_token(db, account)
    now = datetime.now(UTC)
    params = {
        "timeMin": now.isoformat(),
        "timeMax": (now + timedelta(days=days_ahead)).isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": "100",
    }
    try:
        with http.client() as c:
            resp = c.get(
                f"{get_settings().google_calendar_base}/calendars/primary/events",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx2.HTTPError as exc:
        raise IntegrationError("Could not reach Google Calendar") from exc
    if resp.status_code != 200:
        raise IntegrationError(f"Google Calendar error ({resp.status_code})")

    created: list[Meeting] = []
    for event in resp.json().get("items", []):
        if event.get("status") == "cancelled":
            continue
        start_raw = event.get("start", {}).get("dateTime")
        if not start_raw:
            continue  # all-day events are not meetings
        attendees = [a.get("email", "") for a in event.get("attendees", []) if a.get("email")]
        existing = db.scalar(
            select(Meeting).where(
                Meeting.workspace_id == workspace_id, Meeting.external_event_id == event["id"]
            )
        )
        if existing:
            continue
        meeting = Meeting(
            workspace_id=workspace_id,
            created_by_id=user.id,
            title=(event.get("summary") or "Untitled meeting")[:300],
            source=MeetingSource.CALENDAR,
            status=MeetingStatus.SCHEDULED,
            scheduled_at=datetime.fromisoformat(start_raw.replace("Z", "+00:00")),
            external_event_id=event["id"],
            attendees=attendees,
            progress=0,
        )
        db.add(meeting)
        created.append(meeting)
    db.flush()
    return created
