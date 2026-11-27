"""Idempotent demo seed: users, a team workspace and three fully processed meetings.

python -m app.seed
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import session_scope
from app.models import (
    ActionItem,
    ActionStatus,
    Meeting,
    MeetingSource,
    MeetingStatus,
    Membership,
    Role,
    User,
)
from app.services.accounts import create_user_with_workspace
from app.services.meetings import rename_speaker
from app.services.pipeline import regenerate_insights, run_pipeline
from app.services.storage import StorageError, get_storage
from app.services.synth import synthesize

log = get_logger("meetmind.seed")
SEED_DIR = Path(__file__).resolve().parent / "seed_data"
DEMO_EMAIL = "demo@meetmind.dev"
DEMO_PASSWORD = "meetmind-demo"  # noqa: S105
# Seeded meeting title -> (sidecar fixture name or None for the bundled WAV, synth seed).
SEED_AUDIO = {
    "Q3 Launch Planning": (None, 0),
    "Weekly Engineering Sync": ("weekly_engineering_sync", 0),
    "Customer Feedback Review": ("customer_feedback_review", 1),
}


def _add_meeting(
    workspace_id: str, user_id: str, title: str, when: datetime, audio: Path, sidecar: Path | None
) -> str:
    storage = get_storage()
    with session_scope() as db:
        meeting = Meeting(
            workspace_id=workspace_id,
            created_by_id=user_id,
            title=title,
            source=MeetingSource.SEED,
            scheduled_at=when,
            original_filename=audio.name,
            content_type="audio/wav",
        )
        db.add(meeting)
        db.flush()
        meeting.audio_key = f"{workspace_id}/{meeting.id}/original.wav"
        storage.put_file(meeting.audio_key, audio, "audio/wav")
        if sidecar is not None:
            meeting.sidecar_key = f"{workspace_id}/{meeting.id}/transcript.json"
            storage.put_bytes(meeting.sidecar_key, sidecar.read_bytes(), "application/json")
        meeting_id = meeting.id
    run_pipeline(meeting_id)
    return meeting_id


def seed() -> bool:
    with session_scope() as db:
        if db.scalar(select(User).where(User.email == DEMO_EMAIL)):
            log.info("seed_skipped", reason="demo user exists")
            restore_seed_audio()
            return False
        demo = create_user_with_workspace(
            db, email=DEMO_EMAIL, name="Demo User", password=DEMO_PASSWORD
        )
        ws = db.scalars(select(Membership).where(Membership.user_id == demo.id)).one().workspace
        ws.name = "Acme Product Team"
        alex = create_user_with_workspace(
            db, email="alex@meetmind.dev", name="Alex Rivera", password=DEMO_PASSWORD
        )
        vic = create_user_with_workspace(
            db, email="viewer@meetmind.dev", name="Vic Viewer", password=DEMO_PASSWORD
        )
        db.add(Membership(workspace_id=ws.id, user_id=alex.id, role=Role.MEMBER))
        db.add(Membership(workspace_id=ws.id, user_id=vic.id, role=Role.VIEWER))
        ws_id, demo_id, alex_id = ws.id, demo.id, alex.id

    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    launch = _add_meeting(
        ws_id,
        demo_id,
        "Q3 Launch Planning",
        now - timedelta(days=1, hours=3),
        SEED_DIR / "demo_meeting.wav",
        None,
    )
    with tempfile.TemporaryDirectory() as tmp:
        for i, (name, title, days) in enumerate(
            [
                ("weekly_engineering_sync", "Weekly Engineering Sync", 3),
                ("customer_feedback_review", "Customer Feedback Review", 6),
            ]
        ):
            sidecar = SEED_DIR / f"{name}.json"
            audio = Path(tmp) / f"{name}.wav"
            synthesize(json.loads(sidecar.read_text())["segments"], audio, seed=i)
            _add_meeting(ws_id, demo_id, title, now - timedelta(days=days), audio, sidecar)

    with session_scope() as db:
        meeting = db.get(Meeting, launch)
        if meeting is not None:
            for speaker, name in zip(meeting.speakers, ["Priya", "Marcus", "Raj"], strict=False):
                rename_speaker(db, meeting, speaker.id, name)
            # Regenerate notes so the summary and owners use the real names from the start.
            regenerate_insights(db, meeting)
        items = list(
            db.scalars(
                select(ActionItem)
                .where(ActionItem.workspace_id == ws_id)
                .order_by(ActionItem.created_at)
            )
        )
        if len(items) >= 3:
            items[0].status = ActionStatus.IN_PROGRESS
            items[0].assignee_id = alex_id
            items[-1].status = ActionStatus.DONE
        db.add(
            Meeting(
                workspace_id=ws_id,
                created_by_id=demo_id,
                title="Design Review: Onboarding v2",
                source=MeetingSource.CALENDAR,
                status=MeetingStatus.SCHEDULED,
                scheduled_at=now + timedelta(days=1, hours=2),
                attendees=["demo@meetmind.dev", "alex@meetmind.dev"],
                external_event_id="seed-design-review",
            )
        )
    log.info("seed_complete", workspace_id=ws_id)
    return True


def restore_seed_audio() -> int:
    """Re-create seeded recordings missing from storage (e.g. ephemeral disk on free hosting).

    The database survives restarts but a local storage directory may not; the transcript and notes
    are intact, so only the audio objects (and sidecars) need to be put back for playback.
    """
    storage = get_storage()
    restored = 0
    with session_scope() as db:
        seeded = db.scalars(select(Meeting).where(Meeting.source == MeetingSource.SEED)).all()
        with tempfile.TemporaryDirectory() as tmp:
            for meeting in seeded:
                spec = SEED_AUDIO.get(meeting.title)
                if spec is None or not meeting.audio_key:
                    continue
                try:
                    storage.size(meeting.audio_key)
                    continue
                except StorageError:
                    pass
                name, synth_seed = spec
                if name is None:
                    storage.put_file(meeting.audio_key, SEED_DIR / "demo_meeting.wav", "audio/wav")
                else:
                    sidecar = SEED_DIR / f"{name}.json"
                    audio = Path(tmp) / f"{name}.wav"
                    synthesize(json.loads(sidecar.read_text())["segments"], audio, seed=synth_seed)
                    storage.put_file(meeting.audio_key, audio, "audio/wav")
                    if meeting.sidecar_key:
                        storage.put_bytes(
                            meeting.sidecar_key, sidecar.read_bytes(), "application/json"
                        )
                restored += 1
    if restored:
        log.info("seed_audio_restored", count=restored)
    return restored


if __name__ == "__main__":
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    seed()
