"""Workspace-scoped RBAC checks."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ForbiddenError, NotFoundError
from app.models import ActionItem, Meeting, Membership, Role, User


def membership_for(db: Session, user: User, workspace_id: str) -> Membership:
    membership = db.scalar(
        select(Membership).where(
            Membership.workspace_id == workspace_id, Membership.user_id == user.id
        )
    )
    if membership is None:
        # 404 rather than 403: do not reveal that the workspace exists.
        raise NotFoundError("Workspace not found")
    return membership


def require_role(db: Session, user: User, workspace_id: str, minimum: Role) -> Membership:
    membership = membership_for(db, user, workspace_id)
    if membership.role.rank < minimum.rank:
        raise ForbiddenError(f"This action requires the {minimum.value} role or higher")
    return membership


def meeting_for(db: Session, user: User, meeting_id: str, minimum: Role = Role.VIEWER) -> Meeting:
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise NotFoundError("Meeting not found")
    try:
        require_role(db, user, meeting.workspace_id, minimum)
    except NotFoundError as exc:
        raise NotFoundError("Meeting not found") from exc
    return meeting


def action_item_for(
    db: Session, user: User, item_id: str, minimum: Role = Role.MEMBER
) -> ActionItem:
    item = db.get(ActionItem, item_id)
    if item is None:
        raise NotFoundError("Action item not found")
    try:
        require_role(db, user, item.workspace_id, minimum)
    except NotFoundError as exc:
        raise NotFoundError("Action item not found") from exc
    return item
