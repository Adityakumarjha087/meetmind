"""Meeting mutations that must keep derived data consistent (speaker renames)."""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationFailed
from app.models import ActionItem, Meeting, Speaker, TranscriptChunk


def rename_speaker(db: Session, meeting: Meeting, speaker_id: str, new_name: str) -> Speaker:
    new_name = new_name.strip()
    if not new_name:
        raise ValidationFailed("Speaker name cannot be empty")
    speaker = db.get(Speaker, speaker_id)
    if speaker is None or speaker.meeting_id != meeting.id:
        raise NotFoundError("Speaker not found")
    old = speaker.display_name
    if old == new_name:
        return speaker
    speaker.display_name = new_name

    # Propagate to action-item owners, stored insights and RAG chunks.
    db.execute(
        update(ActionItem)
        .where(ActionItem.meeting_id == meeting.id, ActionItem.owner_name == old)
        .values(owner_name=new_name)
    )
    if meeting.insights:
        data: dict[str, Any] = copy.deepcopy(meeting.insights)
        for item in data.get("action_items", []):
            if item.get("owner") == old:
                item["owner"] = new_name
        for s in data.get("sentiment", []):
            if s.get("speaker") == old:
                s["speaker"] = new_name
        meeting.insights = data
    for chunk in db.scalars(
        select(TranscriptChunk).where(TranscriptChunk.meeting_id == meeting.id)
    ):
        if old in (chunk.speakers or []):
            chunk.speakers = sorted(new_name if s == old else s for s in list(chunk.speakers))
            chunk.text = chunk.text.replace(f"{old}:", f"{new_name}:")
    db.flush()
    return speaker
