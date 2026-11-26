from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import AuthError
from app.core.security import decode_token
from app.db.session import get_db
from app.models import User

bearer = HTTPBearer(auto_error=False)

DB = Annotated[Session, Depends(get_db)]


def get_current_user(
    request: Request,
    db: DB,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise AuthError("Missing bearer token")
    payload = decode_token(creds.credentials, "access")
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise AuthError("User not found or disabled")
    request.state.user_id = user.id
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
