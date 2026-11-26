from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DB, CurrentUser
from app.api.routes.meetings import summary_out
from app.models import Role
from app.schemas.api import CalendarImportIn, CalendarImportOut
from app.services.access import require_role
from app.services.google import import_calendar_events

router = APIRouter(tags=["integrations"])


@router.post("/workspaces/{workspace_id}/integrations/google-calendar/import", response_model=CalendarImportOut)
def import_calendar(workspace_id: str, body: CalendarImportIn, user: CurrentUser, db: DB) -> CalendarImportOut:
    require_role(db, user, workspace_id, Role.MEMBER)
    meetings = import_calendar_events(db, user, workspace_id, body.days_ahead)
    db.commit()
    return CalendarImportOut(imported=len(meetings), meetings=[summary_out(m) for m in meetings])
