from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DB
from app.core.errors import GoneError, NotFoundError
from app.models import ActionItem, Meeting
from app.schemas.api import PublicMeetingOut
from app.services.pipeline import insights_of

router = APIRouter(prefix="/share", tags=["share"])


@router.get("/{token}", response_model=PublicMeetingOut)
def shared_meeting(token: str, db: DB) -> PublicMeetingOut:
    """Read-only, unauthenticated summary for share links (no transcript or audio)."""
    if len(token) < 16:
        raise NotFoundError("Shared meeting not found")
    meeting = db.scalar(select(Meeting).where(Meeting.share_token == token))
    if meeting is None:
        raise NotFoundError("Shared meeting not found")
    expires = meeting.share_expires_at
    if expires is not None and (
        expires if expires.tzinfo else expires.replace(tzinfo=UTC)
    ) <= datetime.now(UTC):
        raise GoneError("This share link has expired")
    items = db.scalars(
        select(ActionItem).where(ActionItem.meeting_id == meeting.id).order_by(ActionItem.position)
    )
    return PublicMeetingOut(
        title=meeting.title,
        created_at=meeting.created_at,
        scheduled_at=meeting.scheduled_at,
        duration_s=meeting.duration_s,
        insights=insights_of(meeting),
        action_items=[
            {
                "title": i.title,
                "owner_name": i.owner_name,
                "due_date": i.due_date.isoformat() if i.due_date else None,
                "status": i.status.value,
            }
            for i in items
        ],
        speakers=[s.display_name for s in meeting.speakers],
    )
