from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.core.errors import AppError, AuthError
from app.core.logging import get_logger
from app.models import OAuthAccount, User
from app.schemas.api import GoogleAuthUrlOut, LoginIn, RefreshIn, RegisterIn, TokenOut, UserOut
from app.services import accounts, google

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger(__name__)


def user_out(db: DB, user: User) -> UserOut:
    connected = (
        db.scalar(select(OAuthAccount.id).where(OAuthAccount.user_id == user.id, OAuthAccount.provider == "google"))
        is not None
    )
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
        has_password=bool(user.password_hash),
        google_connected=connected,
    )


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.refresh_cookie_name,
        token,
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        path=f"{settings.api_prefix}/auth",
    )


def _token_response(db: DB, response: Response, user: User, access: str, refresh: str) -> TokenOut:
    _set_refresh_cookie(response, refresh)
    return TokenOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=get_settings().access_token_ttl_minutes * 60,
        user=user_out(db, user),
    )


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, request: Request, response: Response, db: DB) -> TokenOut:
    user = accounts.create_user_with_workspace(db, email=body.email, name=body.name, password=body.password)
    access, refresh = accounts.issue_tokens(db, user, request.headers.get("user-agent"))
    db.commit()
    log.info("user_registered", user_id=user.id)
    return _token_response(db, response, user, access, refresh)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, response: Response, db: DB) -> TokenOut:
    user = accounts.authenticate(db, body.email, body.password)
    access, refresh = accounts.issue_tokens(db, user, request.headers.get("user-agent"))
    db.commit()
    return _token_response(db, response, user, access, refresh)


@router.post("/refresh", response_model=TokenOut)
def refresh(request: Request, response: Response, db: DB, body: RefreshIn | None = None) -> TokenOut:
    """Rotate the refresh token. Accepts the httpOnly cookie (browser) or a JSON body (API clients)."""
    token = (body.refresh_token if body else None) or request.cookies.get(get_settings().refresh_cookie_name)
    if not token:
        raise AuthError("Missing refresh token")
    user, access, new_refresh = accounts.rotate_refresh_token(db, token, request.headers.get("user-agent"))
    db.commit()
    return _token_response(db, response, user, access, new_refresh)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: DB, body: RefreshIn | None = None) -> Response:
    token = (body.refresh_token if body else None) or request.cookies.get(get_settings().refresh_cookie_name)
    if token:
        accounts.revoke_refresh_token(db, token)
        db.commit()
    response = Response(status_code=204)
    response.delete_cookie(get_settings().refresh_cookie_name, path=f"{get_settings().api_prefix}/auth")
    return response


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser, db: DB) -> UserOut:
    return user_out(db, user)


@router.get("/google/authorize", response_model=GoogleAuthUrlOut)
def google_authorize() -> GoogleAuthUrlOut:
    """Start Google sign-in (also grants read-only Calendar access for meeting import)."""
    return GoogleAuthUrlOut(url=google.authorization_url())


@router.get("/google/link", response_model=GoogleAuthUrlOut)
def google_link(user: CurrentUser) -> GoogleAuthUrlOut:
    """Link Google (Calendar) to the signed-in account."""
    return GoogleAuthUrlOut(url=google.authorization_url(link_user_id=user.id))


@router.get("/google/callback", include_in_schema=False)
def google_callback(request: Request, db: DB, code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    settings = get_settings()
    target = f"{settings.frontend_url.rstrip('/')}/auth/callback"
    if error or not code or not state:
        return RedirectResponse(f"{target}#{urlencode({'error': error or 'missing_code'})}")
    try:
        user = google.exchange_code(db, code, state)
        access, refresh_token = accounts.issue_tokens(db, user, request.headers.get("user-agent"))
        db.commit()
    except AppError as exc:
        db.rollback()
        return RedirectResponse(f"{target}#{urlencode({'error': exc.message})}")
    redirect = RedirectResponse(f"{target}#{urlencode({'access_token': access})}")
    _set_refresh_cookie(redirect, refresh_token)
    return redirect
