from __future__ import annotations

import contextlib
import re
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, or_, select

from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.core.errors import (
    AuthError,
    ConflictError,
    NotFoundError,
    PayloadTooLarge,
    ValidationFailed,
)
from app.core.security import create_token, decode_token, random_token
from app.models import (
    ActionItem,
    Meeting,
    MeetingSource,
    MeetingStatus,
    PipelineStage,
    Role,
    Speaker,
    TranscriptSegment,
)
from app.schemas.api import (
    MeetingDetailOut,
    MeetingPage,
    MeetingSummaryOut,
    MeetingUpdate,
    ProgressOut,
    SegmentOut,
    ShareIn,
    ShareOut,
    SpeakerOut,
    SpeakerUpdate,
)
from app.services import export
from app.services.access import meeting_for, require_role
from app.services.dispatch import enqueue_pipeline
from app.services.meetings import rename_speaker
from app.services.pipeline import insights_of, progress_payload
from app.services.slack import post_meeting_summary, share_url_for
from app.services.storage import StorageError, get_storage

router = APIRouter(tags=["meetings"])

AUDIO_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".ogg",
    ".oga",
    ".opus",
    ".webm",
    ".flac",
    ".mp4",
    ".mov",
    ".mkv",
    ".mpeg",
    ".mpga",
    ".avi",
    ".wma",
    ".aiff",
    ".aif",
}
TRANSCRIPT_EXTENSIONS = {".json", ".srt", ".vtt", ".txt"}
MAX_TRANSCRIPT_BYTES = 5 * 1024 * 1024


def _counts(db: DB, ids: list[str]) -> tuple[dict[str, int], dict[str, int]]:
    if not ids:
        return {}, {}
    ai = dict(
        db.execute(
            select(ActionItem.meeting_id, func.count())
            .where(ActionItem.meeting_id.in_(ids))
            .group_by(ActionItem.meeting_id)
        ).all()
    )
    sp = dict(
        db.execute(
            select(Speaker.meeting_id, func.count())
            .where(Speaker.meeting_id.in_(ids))
            .group_by(Speaker.meeting_id)
        ).all()
    )
    return {str(k): int(v) for k, v in ai.items()}, {str(k): int(v) for k, v in sp.items()}


def summary_out(m: Meeting, ai: int = 0, sp: int = 0) -> MeetingSummaryOut:
    out = MeetingSummaryOut.model_validate(m)
    out.action_item_count, out.speaker_count = ai, sp
    return out


def media_url(meeting: Meeting) -> str | None:
    if not meeting.normalized_key:
        return None
    settings = get_settings()
    token, _, _ = create_token(
        meeting.id, "media", timedelta(minutes=settings.media_token_ttl_minutes)
    )
    return f"{settings.public_api_url.rstrip('/')}{settings.api_prefix}/meetings/{meeting.id}/audio?token={token}"


def detail_out(db: DB, meeting: Meeting) -> MeetingDetailOut:
    ai, sp = _counts(db, [meeting.id])
    base = summary_out(meeting, ai.get(meeting.id, 0), sp.get(meeting.id, 0))
    return MeetingDetailOut(
        **base.model_dump(),
        original_filename=meeting.original_filename,
        audio_url=media_url(meeting),
        waveform_peaks=meeting.waveform_peaks,
        stage_timings=meeting.stage_timings or {},
        stt_backend=meeting.stt_backend,
        diarizer_backend=meeting.diarizer_backend,
        llm_provider=meeting.llm_provider,
        insights=insights_of(meeting),
        speakers=[SpeakerOut.model_validate(s) for s in meeting.speakers],
        share_url=share_url_for(meeting),
    )


async def _save_upload(upload: UploadFile, dest: Path, limit: int) -> int:
    size = 0
    with dest.open("wb") as fh:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise PayloadTooLarge(f"File exceeds the {limit // (1024 * 1024)} MB limit")
            fh.write(chunk)
    if size == 0:
        raise ValidationFailed("Uploaded file is empty")
    return size


def _validate_audio(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    ctype = (upload.content_type or "").lower()
    if suffix not in AUDIO_EXTENSIONS:
        raise ValidationFailed(
            f"Unsupported file type '{suffix or 'unknown'}'. Upload audio or video."
        )
    if ctype and not ctype.startswith(("audio/", "video/", "application/octet-stream")):
        raise ValidationFailed(f"Unsupported content type '{ctype}'")
    return suffix


async def _attach_media(
    db: DB,
    meeting: Meeting,
    file: UploadFile,
    transcript: UploadFile | None,
) -> None:
    settings = get_settings()
    suffix = _validate_audio(file)
    storage = get_storage()
    with tempfile.TemporaryDirectory(prefix="meetmind-upload-") as tmp:
        dest = Path(tmp) / f"original{suffix}"
        size = await _save_upload(file, dest, settings.max_upload_mb * 1024 * 1024)
        key = f"{meeting.workspace_id}/{meeting.id}/original{suffix}"
        storage.put_file(key, dest, file.content_type)
    meeting.audio_key = key
    meeting.size_bytes = size
    meeting.original_filename = (file.filename or f"recording{suffix}")[:300]
    meeting.content_type = file.content_type
    if transcript is not None and transcript.filename:
        t_suffix = Path(transcript.filename).suffix.lower()
        if t_suffix not in TRANSCRIPT_EXTENSIONS:
            raise ValidationFailed("Transcript must be .json, .srt, .vtt or .txt")
        raw = await transcript.read(MAX_TRANSCRIPT_BYTES + 1)
        if len(raw) > MAX_TRANSCRIPT_BYTES:
            raise PayloadTooLarge("Transcript file is too large")
        t_key = f"{meeting.workspace_id}/{meeting.id}/transcript{t_suffix}"
        storage.put_bytes(t_key, raw, "text/plain")
        meeting.sidecar_key = t_key
    meeting.status = MeetingStatus.QUEUED
    meeting.stage = PipelineStage.QUEUED
    meeting.progress = 0
    meeting.status_message = "Queued for processing"
    meeting.error = None


@router.get("/workspaces/{workspace_id}/meetings", response_model=MeetingPage)
def list_meetings(
    workspace_id: str,
    user: CurrentUser,
    db: DB,
    status: MeetingStatus | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MeetingPage:
    require_role(db, user, workspace_id, Role.VIEWER)
    stmt = select(Meeting).where(Meeting.workspace_id == workspace_id)
    if status:
        stmt = stmt.where(Meeting.status == status)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Meeting.title).like(like),
                func.lower(Meeting.original_filename).like(like),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(
            stmt.order_by(func.coalesce(Meeting.scheduled_at, Meeting.created_at).desc())
            .limit(limit)
            .offset(offset)
        )
    )
    ai, sp = _counts(db, [m.id for m in rows])
    return MeetingPage(
        items=[summary_out(m, ai.get(m.id, 0), sp.get(m.id, 0)) for m in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/workspaces/{workspace_id}/meetings", response_model=MeetingDetailOut, status_code=201
)
async def upload_meeting(
    workspace_id: str,
    user: CurrentUser,
    db: DB,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File(description="Audio or video file")],
    title: Annotated[str | None, Form(max_length=300)] = None,
    source: Annotated[Literal["upload", "recording"], Form()] = "upload",
    transcript: Annotated[
        UploadFile | None, File(description="Optional sidecar transcript")
    ] = None,
) -> MeetingDetailOut:
    require_role(db, user, workspace_id, Role.MEMBER)
    default_title = (
        Path(file.filename or "Recording").stem.replace("_", " ").replace("-", " ").strip()
    )
    meeting = Meeting(
        workspace_id=workspace_id,
        created_by_id=user.id,
        title=(title or default_title or "Untitled meeting").strip()[:300],
        source=MeetingSource(source),
    )
    db.add(meeting)
    db.flush()
    await _attach_media(db, meeting, file, transcript)
    db.commit()
    enqueue_pipeline(meeting.id, background)
    db.refresh(meeting)
    return detail_out(db, meeting)


@router.get("/meetings/{meeting_id}", response_model=MeetingDetailOut)
def get_meeting(meeting_id: str, user: CurrentUser, db: DB) -> MeetingDetailOut:
    return detail_out(db, meeting_for(db, user, meeting_id))


@router.patch("/meetings/{meeting_id}", response_model=MeetingDetailOut)
def update_meeting(
    meeting_id: str, body: MeetingUpdate, user: CurrentUser, db: DB
) -> MeetingDetailOut:
    meeting = meeting_for(db, user, meeting_id, Role.MEMBER)
    if body.title is not None:
        meeting.title = body.title.strip()
    db.commit()
    return detail_out(db, meeting)


@router.delete("/meetings/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: str, user: CurrentUser, db: DB) -> Response:
    meeting = meeting_for(db, user, meeting_id, Role.ADMIN)
    prefix = f"{meeting.workspace_id}/{meeting.id}"
    db.delete(meeting)
    db.commit()
    with contextlib.suppress(StorageError):
        get_storage().delete_prefix(prefix)
    return Response(status_code=204)


@router.post("/meetings/{meeting_id}/audio", response_model=MeetingDetailOut)
async def attach_audio(
    meeting_id: str,
    user: CurrentUser,
    db: DB,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    transcript: Annotated[UploadFile | None, File()] = None,
) -> MeetingDetailOut:
    """Attach a recording to a scheduled (e.g. calendar-imported) meeting, or replace its audio."""
    meeting = meeting_for(db, user, meeting_id, Role.MEMBER)
    if meeting.status == MeetingStatus.PROCESSING:
        raise ValidationFailed("Meeting is currently processing")
    await _attach_media(db, meeting, file, transcript)
    db.commit()
    enqueue_pipeline(meeting.id, background)
    return detail_out(db, meeting)


@router.post("/meetings/{meeting_id}/reprocess", response_model=ProgressOut, status_code=202)
def reprocess(
    meeting_id: str, user: CurrentUser, db: DB, background: BackgroundTasks
) -> ProgressOut:
    meeting = meeting_for(db, user, meeting_id, Role.MEMBER)
    if not meeting.audio_key:
        raise ValidationFailed("Meeting has no audio")
    stale_before = datetime.now(UTC) - timedelta(seconds=get_settings().pipeline_stale_after_s)
    updated = (
        meeting.updated_at if meeting.updated_at.tzinfo else meeting.updated_at.replace(tzinfo=UTC)
    )
    in_flight = (
        meeting.status in {MeetingStatus.PROCESSING, MeetingStatus.QUEUED}
        and updated > stale_before
    )
    if in_flight:
        raise ConflictError("Meeting is already queued or processing")
    meeting.status, meeting.stage, meeting.progress = MeetingStatus.QUEUED, PipelineStage.QUEUED, 0
    meeting.status_message = "Queued for reprocessing"
    db.commit()
    enqueue_pipeline(meeting.id, background)
    return ProgressOut.model_validate(progress_payload(meeting))


@router.get("/meetings/{meeting_id}/progress", response_model=ProgressOut)
def progress(meeting_id: str, user: CurrentUser, db: DB) -> ProgressOut:
    return ProgressOut.model_validate(progress_payload(meeting_for(db, user, meeting_id)))


@router.get("/meetings/{meeting_id}/transcript", response_model=list[SegmentOut])
def transcript(meeting_id: str, user: CurrentUser, db: DB) -> list[SegmentOut]:
    meeting_for(db, user, meeting_id)
    rows = db.execute(
        select(TranscriptSegment, Speaker.display_name)
        .outerjoin(Speaker, Speaker.id == TranscriptSegment.speaker_id)
        .where(TranscriptSegment.meeting_id == meeting_id)
        .order_by(TranscriptSegment.idx)
    ).all()
    return [
        SegmentOut(
            id=s.id,
            idx=s.idx,
            start_s=s.start_s,
            end_s=s.end_s,
            text=s.text,
            speaker_id=s.speaker_id,
            speaker_name=name,
            confidence=s.confidence,
        )
        for s, name in rows
    ]


@router.patch("/meetings/{meeting_id}/speakers/{speaker_id}", response_model=SpeakerOut)
def update_speaker(
    meeting_id: str, speaker_id: str, body: SpeakerUpdate, user: CurrentUser, db: DB
) -> SpeakerOut:
    meeting = meeting_for(db, user, meeting_id, Role.MEMBER)
    speaker = rename_speaker(db, meeting, speaker_id, body.display_name)
    db.commit()
    return SpeakerOut.model_validate(speaker)


_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


@router.get("/meetings/{meeting_id}/audio", include_in_schema=True)
def audio(meeting_id: str, request: Request, db: DB, token: str) -> Response:
    """Stream the normalised WAV. Auth via short-lived media token (media elements can't send headers)."""
    claims = decode_token(token, "media")
    if claims["sub"] != meeting_id:
        raise AuthError("Token does not match this meeting")
    meeting = db.get(Meeting, meeting_id)
    if meeting is None or not meeting.normalized_key:
        raise NotFoundError("Audio not available")
    storage = get_storage()
    size = storage.size(meeting.normalized_key)
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"}
    range_header = request.headers.get("range")
    if range_header and (m := _RANGE.fullmatch(range_header.strip())):
        start_s, end_s = m.groups()
        if start_s == "":
            start, end = max(0, size - int(end_s or 0)), size - 1
        else:
            start, end = int(start_s), min(int(end_s) if end_s else size - 1, size - 1)
        if start >= size or start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        data = storage.get_range(meeting.normalized_key, start, end)
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return Response(data, status_code=206, media_type="audio/wav", headers=headers)
    return Response(
        storage.get_bytes(meeting.normalized_key), media_type="audio/wav", headers=headers
    )


def _items(db: DB, meeting_id: str) -> list[ActionItem]:
    return list(
        db.scalars(
            select(ActionItem)
            .where(ActionItem.meeting_id == meeting_id)
            .order_by(ActionItem.position)
        )
    )


@router.get("/meetings/{meeting_id}/export")
def export_meeting(
    meeting_id: str,
    user: CurrentUser,
    db: DB,
    format: Literal["md", "pdf"] = "md",
    transcript: bool = True,
) -> Response:
    meeting = meeting_for(db, user, meeting_id)
    items = _items(db, meeting_id)
    slug = re.sub(r"[^a-z0-9]+", "-", meeting.title.lower()).strip("-") or "meeting"
    if format == "pdf":
        return Response(
            export.to_pdf(meeting, items),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{slug}.pdf"'},
        )
    return PlainTextResponse(
        export.to_markdown(meeting, items, transcript),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{slug}.md"'},
    )


@router.post("/meetings/{meeting_id}/share", response_model=ShareOut)
def share(meeting_id: str, user: CurrentUser, db: DB, body: ShareIn | None = None) -> ShareOut:
    """Create (or extend) a read-only share link. Links expire; revoke with DELETE."""
    meeting = meeting_for(db, user, meeting_id, Role.MEMBER)
    if meeting.status != MeetingStatus.COMPLETED:
        raise ValidationFailed("Only processed meetings can be shared")
    days = (
        body.expires_in_days
        if body and body.expires_in_days
        else get_settings().share_link_default_days
    )
    expired = meeting.share_expires_at is not None and _aware(
        meeting.share_expires_at
    ) <= datetime.now(UTC)
    if not meeting.share_token or expired:
        meeting.share_token = random_token(24)
    meeting.share_expires_at = datetime.now(UTC) + timedelta(days=days)
    db.commit()
    url = share_url_for(meeting)
    assert url is not None and meeting.share_token is not None
    return ShareOut(
        share_token=meeting.share_token, share_url=url, expires_at=meeting.share_expires_at
    )


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@router.delete("/meetings/{meeting_id}/share", status_code=204)
def unshare(meeting_id: str, user: CurrentUser, db: DB) -> Response:
    meeting = meeting_for(db, user, meeting_id, Role.MEMBER)
    meeting.share_token = None
    meeting.share_expires_at = None
    db.commit()
    return Response(status_code=204)


@router.post("/meetings/{meeting_id}/slack", status_code=202)
def post_to_slack(meeting_id: str, user: CurrentUser, db: DB) -> dict[str, bool]:
    meeting = meeting_for(db, user, meeting_id, Role.MEMBER)
    if meeting.status != MeetingStatus.COMPLETED:
        raise ValidationFailed("Meeting has not finished processing")
    post_meeting_summary(db, meeting)
    return {"posted": True}
