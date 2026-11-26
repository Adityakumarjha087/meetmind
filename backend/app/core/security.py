"""Password hashing and JWT helpers (access, refresh, media and OAuth-state tokens)."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import get_settings
from app.core.errors import AuthError

TokenType = Literal["access", "refresh", "media", "oauth_state"]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def random_token(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)


def create_token(
    subject: str,
    token_type: TokenType,
    ttl: timedelta,
    extra: dict[str, Any] | None = None,
) -> tuple[str, str, datetime]:
    """Return (encoded_jwt, jti, expires_at)."""
    settings = get_settings()
    now = datetime.now(UTC)
    expires = now + ttl
    jti = uuid.uuid4().hex
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": jti,
        "iss": "meetmind",
    }
    if extra:
        payload.update(extra)
    encoded = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return encoded, jti, expires


def create_access_token(user_id: str) -> str:
    ttl = timedelta(minutes=get_settings().access_token_ttl_minutes)
    return create_token(user_id, "access", ttl)[0]


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer="meetmind",
            options={"require": ["exp", "sub", "type", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("Invalid token") from exc
    if payload.get("type") != expected_type:
        raise AuthError("Wrong token type")
    return payload
