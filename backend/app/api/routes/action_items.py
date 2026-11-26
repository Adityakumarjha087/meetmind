from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.core.errors import NotFoundError, ValidationFailed
from app.models import ActionItem, ActionStatus, Meeting, Membership, Role, User
from app.schemas.api import ActionItemCreate, ActionItemOut, ActionItemUpdate
from app.services.access import action_item_for, require_role

router = APIRouter(tags=["action-items"])


def _out(item: ActionItem) -> ActionItemOut:
    out = ActionItemOut.model_validate(item)
    out.meeting_title = item.meeting.title if item.meeting else None
    out.assignee_name = item.assignee.name if item.assignee else None
    return out


def _check_assignee(db: DB, workspace_id: str, assignee_id: str | None) -> None:
    if assignee_id is None:
        return
    member = db.scalar(
        select(Membership).where(Membership.workspace_id == workspace_id, Membership.user_id == assignee_id)
    )
    if member is None:
        raise ValidationFailed("Assignee must be a member of this workspace")


@router.get("/workspaces/{workspace_id}/action-items", response_model=list[ActionItemOut])
def list_items(
    workspace_id: str,
    user: CurrentUser,
    db: DB,
    status: ActionStatus | None = None,
    meeting_id: str | None = None,
    assignee: Annotated[str | None, Query(description="user id or 'me'")] = None,
) -> list[ActionItemOut]:
    require_role(db, user, workspace_id, Role.VIEWER)
    stmt = select(ActionItem).where(ActionItem.workspace_id == workspace_id)
    if status:
        stmt = stmt.where(ActionItem.status == status)
    if meeting_id:
        stmt = stmt.where(ActionItem.meeting_id == meeting_id)
    if assignee:
        stmt = stmt.where(ActionItem.assignee_id == (user.id if assignee == "me" else assignee))
    rows = db.scalars(stmt.order_by(ActionItem.status, ActionItem.position, ActionItem.created_at))
    return [_out(i) for i in rows]


@router.post("/workspaces/{workspace_id}/action-items", response_model=ActionItemOut, status_code=201)
def create_item(workspace_id: str, body: ActionItemCreate, user: CurrentUser, db: DB) -> ActionItemOut:
    require_role(db, user, workspace_id, Role.MEMBER)
    _check_assignee(db, workspace_id, body.assignee_id)
    if body.meeting_id:
        meeting = db.get(Meeting, body.meeting_id)
        if meeting is None or meeting.workspace_id != workspace_id:
            raise NotFoundError("Meeting not found")
    max_pos = db.scalar(
        select(func.max(ActionItem.position)).where(
            ActionItem.workspace_id == workspace_id, ActionItem.status == body.status
        )
    )
    item = ActionItem(workspace_id=workspace_id, position=(max_pos or 0.0) + 1.0, **body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return _out(item)


@router.patch("/action-items/{item_id}", response_model=ActionItemOut)
def update_item(item_id: str, body: ActionItemUpdate, user: CurrentUser, db: DB) -> ActionItemOut:
    item = action_item_for(db, user, item_id, Role.MEMBER)
    data = body.model_dump(exclude_unset=True)
    if "assignee_id" in data:
        _check_assignee(db, item.workspace_id, data["assignee_id"])
        if data["assignee_id"] and not data.get("owner_name"):
            assignee = db.get(User, data["assignee_id"])
            data["owner_name"] = assignee.name if assignee else item.owner_name
    for key, value in data.items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return _out(item)


@router.delete("/action-items/{item_id}", status_code=204)
def delete_item(item_id: str, user: CurrentUser, db: DB) -> Response:
    item = action_item_for(db, user, item_id, Role.MEMBER)
    db.delete(item)
    db.commit()
    return Response(status_code=204)
