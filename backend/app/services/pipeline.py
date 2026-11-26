"""Background meeting pipeline.

normalise (FFmpeg) -> transcribe -> diarize -> merge -> summarise (single-pass / map-reduce)
-> index (embeddings for RAG) -> done.  Every stage commits its progress so that clients see
live updates via Socket.IO and polling alike; failures are captured on the meeting row.
"""

from __future__ import annotations

import hashlib
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.base import new_id
from app.db.session import session_scope
from app.embeddings.base import Embedder
from app.embeddings.factory import build_embedder
from app.intelligence.factory import build_engine
from app.intelligence.heuristic import HeuristicEngine
from app.intelligence.summarizer import summarize
from app.intelligence.types import AnalysisInput, InsightEngine, LLMUsage, TranscriptLine
from app.llm.base import LLMError
from app.models import (
    ActionItem,
    ActionStatus,
    Meeting,
    MeetingStatus,
    PipelineStage,
    Speaker,
    TranscriptChunk,
    TranscriptSegment,
    UsageEvent,
    UsageKind,
    Workspace,
)
from app.schemas.insights import Insights
from app.services import costs
from app.services.audio import compute_peaks, normalize_audio, read_wav
from app.services.progress import PROGRESS_EVENT, Emitter, get_emitter
from app.services.storage import ObjectStorage, get_storage
from app.stt.base import Diarizer, LabelledSegment, Transcriber, TranscriptionContext
from app.stt.factory import build_diarizer, build_transcriber
from app.stt.merge import assign_speakers, speaker_name_hints

log = get_logger(__name__)

STAGE_PROGRESS: dict[PipelineStage, int] = {
    PipelineStage.QUEUED: 0,
    PipelineStage.NORMALIZE: 5,
    PipelineStage.TRANSCRIBE: 20,
    PipelineStage.DIARIZE: 45,
    PipelineStage.MERGE: 60,
    PipelineStage.SUMMARIZE: 70,
    PipelineStage.INDEX: 88,
    PipelineStage.DONE: 100,
}
STAGE_MESSAGES: dict[PipelineStage, str] = {
    PipelineStage.NORMALIZE: "Normalising audio",
    PipelineStage.TRANSCRIBE: "Transcribing speech",
    PipelineStage.DIARIZE: "Identifying speakers",
    PipelineStage.MERGE: "Building speaker-labelled transcript",
    PipelineStage.SUMMARIZE: "Generating summary and action items",
    PipelineStage.INDEX: "Indexing for search",
    PipelineStage.DONE: "Complete",
}


@dataclass
class PipelineDeps:
    settings: Settings
    storage: ObjectStorage
    transcriber: Transcriber
    diarizer: Diarizer
    engine: InsightEngine
    embedder: Embedder
    emitter: Emitter
    session_factory: Callable[[], Any] = session_scope


@lru_cache
def _cached_backends() -> tuple[Transcriber, Diarizer]:
    settings = get_settings()
    return build_transcriber(settings), build_diarizer(settings)


def default_deps() -> PipelineDeps:
    settings = get_settings()
    transcriber, diarizer = _cached_backends()
    return PipelineDeps(
        settings=settings,
        storage=get_storage(),
        transcriber=transcriber,
        diarizer=diarizer,
        engine=build_engine(settings),
        embedder=build_embedder(settings),
        emitter=get_emitter(),
    )


def progress_payload(meeting: Meeting) -> dict[str, Any]:
    return {
        "meeting_id": meeting.id,
        "workspace_id": meeting.workspace_id,
        "status": meeting.status.value,
        "stage": meeting.stage.value,
        "progress": meeting.progress,
        "message": meeting.status_message,
        "error": meeting.error,
    }


def _emit(deps: PipelineDeps, meeting: Meeting) -> None:
    deps.emitter.emit(
        PROGRESS_EVENT,
        progress_payload(meeting),
        [f"meeting:{meeting.id}", f"workspace:{meeting.workspace_id}"],
    )


def _set_stage(
    deps: PipelineDeps,
    meeting_id: str,
    stage: PipelineStage,
    message: str | None = None,
    run_id: str | None = None,
) -> None:
    with deps.session_factory() as db:
        meeting = _owned(db, meeting_id, run_id) if run_id else db.get(Meeting, meeting_id)
        if meeting is None:
            return
        meeting.stage = stage
        meeting.progress = STAGE_PROGRESS[stage]
        meeting.status_message = message or STAGE_MESSAGES.get(stage)
        if stage != PipelineStage.DONE:
            meeting.status = MeetingStatus.PROCESSING
        db.flush()
        _emit(deps, meeting)


def build_chunks(
    lines: list[TranscriptLine], target_words: int = 120
) -> list[list[TranscriptLine]]:
    """Group consecutive lines into ~target_words windows with a one-line overlap."""
    chunks: list[list[TranscriptLine]] = []
    current: list[TranscriptLine] = []
    count = 0
    for ln in lines:
        current.append(ln)
        count += len(ln.text.split())
        if count >= target_words:
            chunks.append(current)
            current = [current[-1]]
            count = len(current[0].text.split())
    if current and (not chunks or current != chunks[-1][-1:]):
        chunks.append(current)
    return chunks


def record_llm_usage(
    db: Session,
    settings: Settings,
    workspace_id: str,
    meeting_id: str | None,
    usage: list[LLMUsage],
) -> None:
    for u in usage:
        db.add(
            UsageEvent(
                workspace_id=workspace_id,
                meeting_id=meeting_id,
                kind=UsageKind.LLM,
                provider=u.provider,
                model=u.model,
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                duration_ms=u.latency_ms,
                cost_usd=costs.llm_cost(
                    settings, u.provider, u.model, u.input_tokens, u.output_tokens
                ),
                projected_cost_usd=costs.llm_projected_cost(
                    settings, u.input_tokens, u.output_tokens
                ),
            )
        )


def _speaker_names(labelled: list[LabelledSegment], hints: dict[str, str]) -> dict[str, str]:
    names: dict[str, str] = {}
    for seg in labelled:
        if seg.speaker not in names:
            names[seg.speaker] = hints.get(seg.speaker) or f"Speaker {len(names) + 1}"
    return names


class Superseded(RuntimeError):
    """Another pipeline run claimed this meeting (e.g. after crash recovery); stop quietly."""


def _claim(deps: PipelineDeps, meeting_id: str, run_id: str) -> bool:
    """Atomically take ownership of a queued (or stale processing) meeting.

    The conditional UPDATE makes concurrent deliveries of the same job safe: exactly one
    run wins, the others see rowcount == 0 and exit without touching the meeting.
    """
    stale_before = datetime.now(UTC) - timedelta(seconds=deps.settings.pipeline_stale_after_s)
    with deps.session_factory() as db:
        result = db.execute(
            update(Meeting)
            .where(
                Meeting.id == meeting_id,
                Meeting.audio_key.is_not(None),
                or_(
                    Meeting.status.in_([MeetingStatus.QUEUED, MeetingStatus.FAILED]),
                    and_(
                        Meeting.status == MeetingStatus.PROCESSING,
                        Meeting.updated_at < stale_before,
                    ),
                ),
            )
            .values(
                status=MeetingStatus.PROCESSING,
                pipeline_run_id=run_id,
                updated_at=datetime.now(UTC),
            )
            .execution_options(synchronize_session=False)
        )
        return bool(getattr(result, "rowcount", 0) == 1)


def _owned(db: Session, meeting_id: str, run_id: str) -> Meeting:
    m = db.get(Meeting, meeting_id)
    if m is None or m.pipeline_run_id != run_id:
        raise Superseded(meeting_id)
    return m


def recover_stale_meetings(session_factory: Callable[[], Any] = session_scope) -> list[str]:
    """Re-queue meetings whose worker died mid-pipeline (no heartbeat within the stale window)."""
    settings = get_settings()
    stale_before = datetime.now(UTC) - timedelta(seconds=settings.pipeline_stale_after_s)
    with session_factory() as db:
        ids = list(
            db.scalars(
                select(Meeting.id).where(
                    Meeting.status == MeetingStatus.PROCESSING, Meeting.updated_at < stale_before
                )
            )
        )
        if ids:
            db.execute(
                update(Meeting)
                .where(Meeting.id.in_(ids))
                .values(
                    status=MeetingStatus.QUEUED,
                    stage=PipelineStage.QUEUED,
                    progress=0,
                    status_message="Re-queued after an interrupted run",
                    pipeline_run_id=None,
                )
                .execution_options(synchronize_session=False)
            )
    if ids:
        log.warning("pipeline_recovered_stale", meetings=ids)
    return ids


def run_pipeline(meeting_id: str, deps: PipelineDeps | None = None) -> None:
    deps = deps or default_deps()
    timings: dict[str, float] = {}
    started = datetime.now(UTC)
    run_id = new_id()
    with deps.session_factory() as db:
        meeting = db.get(Meeting, meeting_id)
        if meeting is None:
            log.warning("pipeline_missing_meeting", meeting_id=meeting_id)
            return
        if not meeting.audio_key:
            meeting.status = MeetingStatus.FAILED
            meeting.stage = PipelineStage.FAILED
            meeting.error = "No audio attached to this meeting"
            return
    if not _claim(deps, meeting_id, run_id):
        log.info("pipeline_skip_not_claimable", meeting_id=meeting_id)
        return
    with deps.session_factory() as db:
        meeting = _owned(db, meeting_id, run_id)
        meeting.error = None
        meeting.processing_started_at = started
        meeting.processing_finished_at = None
        meeting.stt_backend = deps.transcriber.name
        meeting.diarizer_backend = deps.diarizer.name
        meeting.llm_provider = deps.engine.name
        workspace_id = meeting.workspace_id
        audio_key = meeting.audio_key
        assert audio_key is not None  # guaranteed by _claim
        sidecar_key = meeting.sidecar_key
        title = meeting.title
        meeting_date: date = (meeting.scheduled_at or meeting.created_at or started).date()
        original_name = meeting.original_filename or "audio"

    log.info("pipeline_start", meeting_id=meeting_id)
    try:
        with tempfile.TemporaryDirectory(prefix="meetmind-") as tmp:
            tmpdir = Path(tmp)
            # 1. normalise -------------------------------------------------------------
            _set_stage(deps, meeting_id, PipelineStage.NORMALIZE, run_id=run_id)
            t0 = time.perf_counter()
            src = deps.storage.download(audio_key, tmpdir / f"original{Path(original_name).suffix}")
            sha = hashlib.sha256(src.read_bytes()).hexdigest()
            normalized = tmpdir / "normalized.wav"
            method = normalize_audio(src, normalized, deps.settings.target_sample_rate)
            norm_key = f"{workspace_id}/{meeting_id}/normalized.wav"
            deps.storage.put_file(norm_key, normalized, "audio/wav")
            audio = read_wav(normalized)
            peaks = compute_peaks(audio.samples)
            timings["normalize"] = time.perf_counter() - t0
            with deps.session_factory() as db:
                m = _owned(db, meeting_id, run_id)
                m.normalized_key = norm_key
                m.duration_s = round(audio.duration_s, 3)
                m.waveform_peaks = peaks
                m.audio_sha256 = sha
            log.info(
                "pipeline_normalized",
                meeting_id=meeting_id,
                method=method,
                duration_s=audio.duration_s,
            )

            # 2. transcribe ------------------------------------------------------------
            _set_stage(deps, meeting_id, PipelineStage.TRANSCRIBE, run_id=run_id)
            t0 = time.perf_counter()
            sidecar_text = (
                deps.storage.get_bytes(sidecar_key).decode("utf-8", "replace")
                if sidecar_key
                else None
            )
            ctx = TranscriptionContext(
                audio_path=normalized,
                audio=audio,
                original_sha256=sha,
                sidecar_text=sidecar_text,
                sidecar_filename=Path(sidecar_key).name if sidecar_key else None,
            )
            pieces = deps.transcriber.transcribe(ctx)
            timings["transcribe"] = time.perf_counter() - t0

            # 3. diarize ---------------------------------------------------------------
            _set_stage(deps, meeting_id, PipelineStage.DIARIZE, run_id=run_id)
            t0 = time.perf_counter()
            turns = deps.diarizer.diarize(audio, normalized)
            timings["diarize"] = time.perf_counter() - t0

        # 4. merge -----------------------------------------------------------------------
        _set_stage(deps, meeting_id, PipelineStage.MERGE, run_id=run_id)
        t0 = time.perf_counter()
        labelled = assign_speakers(pieces, turns)
        names = _speaker_names(labelled, speaker_name_hints(pieces, labelled))
        lines = [TranscriptLine(s.start, s.end, names[s.speaker], s.text) for s in labelled]
        with deps.session_factory() as db:
            _owned(db, meeting_id, run_id)
            db.execute(delete(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting_id))
            db.execute(delete(Speaker).where(Speaker.meeting_id == meeting_id))
            speakers: dict[str, Speaker] = {}
            for label, display in names.items():
                segs = [s for s in labelled if s.speaker == label]
                sp = Speaker(
                    meeting_id=meeting_id,
                    label=label,
                    display_name=display,
                    talk_time_s=round(sum(s.end - s.start for s in segs), 2),
                    word_count=sum(len(s.text.split()) for s in segs),
                )
                db.add(sp)
                speakers[label] = sp
            db.flush()
            for idx, s in enumerate(labelled):
                db.add(
                    TranscriptSegment(
                        meeting_id=meeting_id,
                        speaker_id=speakers[s.speaker].id,
                        idx=idx,
                        start_s=round(s.start, 3),
                        end_s=round(s.end, 3),
                        text=s.text,
                        confidence=s.confidence,
                    )
                )
            db.add(
                UsageEvent(
                    workspace_id=workspace_id,
                    meeting_id=meeting_id,
                    kind=UsageKind.STT,
                    provider=deps.transcriber.name,
                    audio_seconds=audio.duration_s,
                    duration_ms=timings["transcribe"] * 1000,
                    cost_usd=costs.stt_cost(deps.settings, deps.transcriber.name, audio.duration_s),
                    projected_cost_usd=costs.stt_projected_cost(deps.settings, audio.duration_s),
                )
            )
            db.add(
                UsageEvent(
                    workspace_id=workspace_id,
                    meeting_id=meeting_id,
                    kind=UsageKind.DIARIZATION,
                    provider=deps.diarizer.name,
                    audio_seconds=audio.duration_s,
                    duration_ms=timings["diarize"] * 1000,
                )
            )
        timings["merge"] = time.perf_counter() - t0

        # 5. summarise -------------------------------------------------------------------
        _set_stage(deps, meeting_id, PipelineStage.SUMMARIZE, run_id=run_id)
        t0 = time.perf_counter()
        analysis = AnalysisInput(title, meeting_date, lines)
        fallback_note: str | None = None
        try:
            result = summarize(
                deps.engine,
                analysis,
                long_threshold_s=deps.settings.long_meeting_threshold_s,
                chunk_s=deps.settings.map_chunk_s,
            )
        except LLMError as exc:
            if not deps.settings.llm_fallback_offline:
                raise
            log.warning("llm_failed_falling_back", meeting_id=meeting_id, error=str(exc))
            fallback_note = f"AI provider failed ({exc}); notes generated by the offline engine"
            result = summarize(
                HeuristicEngine(),
                analysis,
                long_threshold_s=deps.settings.long_meeting_threshold_s,
                chunk_s=deps.settings.map_chunk_s,
            )
            result.insights.engine = "offline (fallback)"
        timings["summarize"] = time.perf_counter() - t0
        with deps.session_factory() as db:
            m = _owned(db, meeting_id, run_id)
            m.insights = result.insights.model_dump(mode="json")
            db.execute(delete(ActionItem).where(ActionItem.meeting_id == meeting_id))
            for pos, item in enumerate(result.insights.action_items):
                db.add(
                    ActionItem(
                        workspace_id=workspace_id,
                        meeting_id=meeting_id,
                        title=item.title,
                        owner_name=item.owner,
                        due_date=item.due_date,
                        status=ActionStatus.TODO,
                        position=float(pos),
                        source_start_s=item.timestamp_s,
                    )
                )
            record_llm_usage(db, deps.settings, workspace_id, meeting_id, result.usage)

        # 6. index -----------------------------------------------------------------------
        _set_stage(deps, meeting_id, PipelineStage.INDEX, run_id=run_id)
        t0 = time.perf_counter()
        chunks = build_chunks(lines, deps.settings.chunk_target_words)
        texts = [" ".join(f"{ln.speaker}: {ln.text}" for ln in ch) for ch in chunks]
        vectors = deps.embedder.embed(texts) if texts else []
        with deps.session_factory() as db:
            _owned(db, meeting_id, run_id)
            db.execute(delete(TranscriptChunk).where(TranscriptChunk.meeting_id == meeting_id))
            for ch, text, vec in zip(chunks, texts, vectors, strict=True):
                db.add(
                    TranscriptChunk(
                        meeting_id=meeting_id,
                        workspace_id=workspace_id,
                        start_s=ch[0].start,
                        end_s=ch[-1].end,
                        speakers=sorted({ln.speaker for ln in ch}),
                        text=text,
                        embedding=vec,
                    )
                )
            db.add(
                UsageEvent(
                    workspace_id=workspace_id,
                    meeting_id=meeting_id,
                    kind=UsageKind.EMBEDDING,
                    provider=deps.embedder.name,
                    input_tokens=sum(len(t) // 4 for t in texts),
                    duration_ms=(time.perf_counter() - t0) * 1000,
                )
            )
        timings["index"] = time.perf_counter() - t0

        # 7. done ------------------------------------------------------------------------
        with deps.session_factory() as db:
            m = _owned(db, meeting_id, run_id)
            m.status = MeetingStatus.COMPLETED
            m.stage = PipelineStage.DONE
            m.progress = 100
            m.status_message = fallback_note or STAGE_MESSAGES[PipelineStage.DONE]
            m.processing_finished_at = datetime.now(UTC)
            m.stage_timings = {k: round(v, 4) for k, v in timings.items()}
            db.flush()
            _emit(deps, m)
            ws = db.get(Workspace, workspace_id)
            auto_slack = bool(ws and ws.slack_auto_post and ws.slack_webhook_url)
        log.info("pipeline_done", meeting_id=meeting_id, timings=timings)
        if auto_slack:
            _auto_post_slack(meeting_id)
    except Superseded:
        log.warning("pipeline_superseded", meeting_id=meeting_id, run_id=run_id)
    except Exception as exc:
        log.exception("pipeline_failed", meeting_id=meeting_id)
        with deps.session_factory() as db:
            m = db.get(Meeting, meeting_id)
            if m is not None and m.pipeline_run_id == run_id:
                m.status = MeetingStatus.FAILED
                m.stage = PipelineStage.FAILED
                m.error = str(exc)[:2000] or exc.__class__.__name__
                m.status_message = "Processing failed"
                m.processing_finished_at = datetime.now(UTC)
                m.stage_timings = {k: round(v, 4) for k, v in timings.items()}
                db.flush()
                _emit(deps, m)


def _auto_post_slack(meeting_id: str) -> None:
    from app.services.slack import post_meeting_summary

    try:
        with session_scope() as db:
            meeting = db.get(Meeting, meeting_id)
            if meeting is not None:
                post_meeting_summary(db, meeting)
    except Exception:
        log.warning("slack_auto_post_failed", meeting_id=meeting_id)


def insights_of(meeting: Meeting) -> Insights | None:
    return Insights.model_validate(meeting.insights) if meeting.insights else None
