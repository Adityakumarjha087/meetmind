"""User registration, credential checks and refresh-token rotation with reuse detection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AuthError, ConflictError
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.base import new_id
from app.models import Membership, RefreshToken, Role, User, Workspace

log = get_logger(__name__)
_DUMMY_HASH = hash_password("timing-equaliser")


def create_user_with_workspace(db: Session, *, email: str, name: str, password: str | None) -> User:
    email = email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise ConflictError("An account with this email already exists")
    user = User(
        email=email, name=name.strip(), password_hash=hash_password(password) if password else None
    )
    db.add(user)
    db.flush()
    workspace = Workspace(name=f"{user.name.split(' ')[0]}'s workspace")
    db.add(workspace)
    db.flush()
    db.add(Membership(workspace_id=workspace.id, user_id=user.id, role=Role.OWNER))
    db.flush()
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        verify_password(password, _DUMMY_HASH)  # constant-ish time for unknown emails
        raise AuthError("Invalid email or password")
    if not verify_password(password, user.password_hash) or not user.is_active:
        raise AuthError("Invalid email or password")
    return user


def issue_tokens(
    db: Session, user: User, user_agent: str | None = None, family: str | None = None
) -> tuple[str, str]:
    settings = get_settings()
    fam = family or new_id()
    refresh, jti, expires = create_token(
        user.id, "refresh", timedelta(days=settings.refresh_token_ttl_days), {"fam": fam}
    )
    db.add(
        RefreshToken(
            user_id=user.id,
            jti=jti,
            family=fam,
            expires_at=expires,
            created_at=datetime.now(UTC),
            user_agent=(user_agent or "")[:300] or None,
        )
    )
    db.flush()
    return create_access_token(user.id), refresh


def rotate_refresh_token(
    db: Session, token: str, user_agent: str | None = None
) -> tuple[User, str, str]:
    claims = decode_token(token, "refresh")
    record = db.scalar(select(RefreshToken).where(RefreshToken.jti == claims["jti"]))
    if record is None:
        raise AuthError("Unknown refresh token")
    if record.revoked_at is not None:
        # Reuse of a rotated token => likely theft. Revoke the whole family.
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.family == record.family, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        db.commit()
        log.warning("refresh_token_reuse_detected", user_id=record.user_id)
        raise AuthError("Refresh token reuse detected; please sign in again")
    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise AuthError("Account disabled")
    record.revoked_at = datetime.now(UTC)
    access, refresh = issue_tokens(db, user, user_agent, family=record.family)
    return user, access, refresh


def revoke_refresh_token(db: Session, token: str) -> None:
    try:
        claims = decode_token(token, "refresh")
    except AuthError:
        return
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.jti == claims["jti"], RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
