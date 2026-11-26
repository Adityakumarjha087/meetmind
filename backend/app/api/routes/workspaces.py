from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationFailed
from app.models import Membership, OAuthAccount, Role, User, Workspace
from app.schemas.api import (
    IntegrationStatusOut,
    MemberIn,
    MemberOut,
    MemberUpdate,
    WorkspaceIn,
    WorkspaceOut,
    WorkspaceUpdate,
)
from app.services.access import membership_for, require_role
from app.services.slack import validate_webhook_url
from app.services.usage_stats import workspace_usage

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _out(db: DB, ws: Workspace, role: Role) -> WorkspaceOut:
    count = (
        db.scalar(
            select(func.count()).select_from(Membership).where(Membership.workspace_id == ws.id)
        )
        or 0
    )
    return WorkspaceOut(
        id=ws.id,
        name=ws.name,
        role=role,
        slack_configured=bool(ws.slack_webhook_url),
        slack_auto_post=ws.slack_auto_post,
        member_count=count,
        created_at=ws.created_at,
    )


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(user: CurrentUser, db: DB) -> list[WorkspaceOut]:
    rows = db.execute(
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == user.id)
        .order_by(Workspace.created_at)
    ).all()
    return [_out(db, ws, role) for ws, role in rows]


@router.post("", response_model=WorkspaceOut, status_code=201)
def create_workspace(body: WorkspaceIn, user: CurrentUser, db: DB) -> WorkspaceOut:
    ws = Workspace(name=body.name.strip())
    db.add(ws)
    db.flush()
    db.add(Membership(workspace_id=ws.id, user_id=user.id, role=Role.OWNER))
    db.commit()
    return _out(db, ws, Role.OWNER)


@router.get("/{workspace_id}", response_model=WorkspaceOut)
def get_workspace(workspace_id: str, user: CurrentUser, db: DB) -> WorkspaceOut:
    m = membership_for(db, user, workspace_id)
    return _out(db, m.workspace, m.role)


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
def update_workspace(
    workspace_id: str, body: WorkspaceUpdate, user: CurrentUser, db: DB
) -> WorkspaceOut:
    m = require_role(db, user, workspace_id, Role.ADMIN)
    ws = m.workspace
    if body.name is not None:
        ws.name = body.name.strip()
    if body.slack_webhook_url is not None:
        url = str(body.slack_webhook_url)
        ws.slack_webhook_url = validate_webhook_url(url) if url else None
    if body.slack_auto_post is not None:
        ws.slack_auto_post = body.slack_auto_post
    db.commit()
    return _out(db, ws, m.role)


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: str, user: CurrentUser, db: DB) -> Response:
    m = require_role(db, user, workspace_id, Role.OWNER)
    owned = db.scalar(
        select(func.count()).select_from(Membership).where(Membership.user_id == user.id)
    )
    if owned is not None and owned <= 1:
        raise ValidationFailed("You cannot delete your only workspace")
    db.delete(m.workspace)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- members
@router.get("/{workspace_id}/members", response_model=list[MemberOut])
def list_members(workspace_id: str, user: CurrentUser, db: DB) -> list[MemberOut]:
    membership_for(db, user, workspace_id)
    rows = db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == workspace_id)
    ).all()
    return [MemberOut(user_id=u.id, email=u.email, name=u.name, role=m.role) for m, u in rows]


@router.post("/{workspace_id}/members", response_model=MemberOut, status_code=201)
def add_member(workspace_id: str, body: MemberIn, user: CurrentUser, db: DB) -> MemberOut:
    actor = require_role(db, user, workspace_id, Role.ADMIN)
    if body.role == Role.OWNER and actor.role != Role.OWNER:
        raise ForbiddenError("Only owners can grant the owner role")
    invitee = db.scalar(select(User).where(User.email == str(body.email).lower()))
    if invitee is None:
        raise NotFoundError("No MeetMind account with that email - ask them to sign up first")
    exists = db.scalar(
        select(Membership).where(
            Membership.workspace_id == workspace_id, Membership.user_id == invitee.id
        )
    )
    if exists:
        raise ConflictError("User is already a member")
    db.add(Membership(workspace_id=workspace_id, user_id=invitee.id, role=body.role))
    db.commit()
    return MemberOut(user_id=invitee.id, email=invitee.email, name=invitee.name, role=body.role)


def _owner_count(db: DB, workspace_id: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.workspace_id == workspace_id, Membership.role == Role.OWNER)
        )
        or 0
    )


@router.patch("/{workspace_id}/members/{user_id}", response_model=MemberOut)
def update_member(
    workspace_id: str, user_id: str, body: MemberUpdate, user: CurrentUser, db: DB
) -> MemberOut:
    actor = require_role(db, user, workspace_id, Role.ADMIN)
    target = db.scalar(
        select(Membership).where(
            Membership.workspace_id == workspace_id, Membership.user_id == user_id
        )
    )
    if target is None:
        raise NotFoundError("Member not found")
    if (Role.OWNER in (target.role, body.role)) and actor.role != Role.OWNER:
        raise ForbiddenError("Only owners can change owner roles")
    if (
        target.role == Role.OWNER
        and body.role != Role.OWNER
        and _owner_count(db, workspace_id) <= 1
    ):
        raise ValidationFailed("A workspace needs at least one owner")
    target.role = body.role
    db.commit()
    return MemberOut(
        user_id=target.user.id, email=target.user.email, name=target.user.name, role=target.role
    )


@router.delete("/{workspace_id}/members/{user_id}", status_code=204)
def remove_member(workspace_id: str, user_id: str, user: CurrentUser, db: DB) -> Response:
    target = db.scalar(
        select(Membership).where(
            Membership.workspace_id == workspace_id, Membership.user_id == user_id
        )
    )
    if user_id != user.id:
        actor = require_role(db, user, workspace_id, Role.ADMIN)
        if target is not None and target.role == Role.OWNER and actor.role != Role.OWNER:
            raise ForbiddenError("Only owners can remove owners")
    else:
        membership_for(db, user, workspace_id)
    if target is None:
        raise NotFoundError("Member not found")
    if target.role == Role.OWNER and _owner_count(db, workspace_id) <= 1:
        raise ValidationFailed("A workspace needs at least one owner")
    db.delete(target)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- usage & integrations
@router.get("/{workspace_id}/usage")
def usage(workspace_id: str, user: CurrentUser, db: DB, days: int = 30) -> dict[str, object]:
    require_role(db, user, workspace_id, Role.MEMBER)
    return workspace_usage(db, workspace_id, max(1, min(days, 365)))


@router.get("/{workspace_id}/integrations", response_model=IntegrationStatusOut)
def integrations(workspace_id: str, user: CurrentUser, db: DB) -> IntegrationStatusOut:
    m = membership_for(db, user, workspace_id)
    settings = get_settings()
    google_acct = db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.user_id == user.id, OAuthAccount.provider == "google"
        )
    )
    return IntegrationStatusOut(
        google_oauth_enabled=settings.google_enabled,
        google_calendar_connected=bool(google_acct and "calendar" in (google_acct.scopes or "")),
        slack_configured=bool(m.workspace.slack_webhook_url),
        llm_provider=settings.llm_provider,
        stt_backend=settings.stt_backend,
        diarizer_backend=settings.diarizer_backend,
        embedding_backend=settings.embedding_backend,
    )
