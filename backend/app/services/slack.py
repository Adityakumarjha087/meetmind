"""Post meeting summaries to a Slack incoming webhook (Block Kit)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx2
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import IntegrationError, ValidationFailed
from app.models import ActionItem, Meeting, Workspace
from app.services import http
from app.services.pipeline import insights_of


def validate_webhook_url(url: str) -> str:
    parsed = urlparse(url)
    allowed = get_settings().slack_allowed_hosts
    if parsed.scheme != "https" or parsed.hostname not in allowed:
        raise ValidationFailed(f"Slack webhook must be an https URL on: {', '.join(allowed)}")
    return url


def esc(text: str) -> str:
    """Escape Slack mrkdwn control characters so transcript text can't inject mentions or links."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_blocks(
    meeting: Meeting, items: list[ActionItem], share_url: str | None
) -> dict[str, Any]:
    insights = insights_of(meeting)
    summary = esc(insights.executive_summary) if insights else "Summary not available yet."
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Meeting notes: {meeting.title}"[:150]},
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": summary[:2900]}},
    ]
    if insights and insights.decisions:
        text = "\n".join(f"• {esc(d.text)}" for d in insights.decisions[:10])
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Decisions*\n{text}"[:2900]}}
        )
    if items:
        lines = []
        for it in items[:15]:
            owner = f" — _{esc(it.owner_name)}_" if it.owner_name else ""
            due = f" (due {it.due_date.isoformat()})" if it.due_date else ""
            lines.append(f"• {esc(it.title)}{owner}{due}")
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Action items*\n" + "\n".join(lines)},
            }
        )
    if share_url:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"<{share_url}|Open in MeetMind>"}],
            }
        )
    return {"text": f"Meeting notes: {meeting.title}", "blocks": blocks}


def share_url_for(meeting: Meeting) -> str | None:
    if not meeting.share_token:
        return None
    return f"{get_settings().frontend_url.rstrip('/')}/share/{meeting.share_token}"


def post_meeting_summary(db: Session, meeting: Meeting) -> None:
    workspace = db.get(Workspace, meeting.workspace_id)
    if workspace is None or not workspace.slack_webhook_url:
        raise ValidationFailed("No Slack webhook configured for this workspace")
    url = validate_webhook_url(workspace.slack_webhook_url)
    items = list(
        db.scalars(
            select(ActionItem)
            .where(ActionItem.meeting_id == meeting.id)
            .order_by(ActionItem.position)
        )
    )
    payload = build_blocks(meeting, items, share_url_for(meeting))
    try:
        with http.client() as c:
            resp = c.post(url, json=payload)
    except httpx2.HTTPError as exc:
        raise IntegrationError("Could not reach Slack") from exc
    if resp.status_code >= 400:
        raise IntegrationError(
            f"Slack rejected the message ({resp.status_code}): {resp.text[:200]}"
        )
