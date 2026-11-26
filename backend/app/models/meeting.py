from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import get_settings
from app.db.base import Base, IdMixin, TimestampMixin
from app.db.types import EmbeddingVector
from app.models.enums import MeetingSource, MeetingStatus, PipelineStage


def _enum(cls: type, name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class Meeting(IdMixin, TimestampMixin, Base):
    __tablename__ = "meetings"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(300))
    source: Mapped[MeetingSource] = mapped_column(
        _enum(MeetingSource, "meeting_source"), default=MeetingSource.UPLOAD
    )
    status: Mapped[MeetingStatus] = mapped_column(
        _enum(MeetingStatus, "meeting_status"), default=MeetingStatus.QUEUED, index=True
    )
    stage: Mapped[PipelineStage] = mapped_column(
        _enum(PipelineStage, "pipeline_stage"), default=PipelineStage.QUEUED
    )
    progress: Mapped[int] = mapped_column(Integer, default=0)
    status_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_event_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    attendees: Mapped[list[str]] = mapped_column(JSON, default=list)

    original_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    audio_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    normalized_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sidecar_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    audio_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    waveform_peaks: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)

    stt_backend: Mapped[str | None] = mapped_column(String(40), nullable=True)
    diarizer_backend: Mapped[str | None] = mapped_column(String(40), nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processing_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stage_timings: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)

    # AI outputs (validated against app.schemas.insights.Insights before being stored)
    insights: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    share_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Identifies the pipeline run that currently owns this meeting (concurrency / crash recovery).
    pipeline_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    speakers: Mapped[list[Speaker]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", order_by="Speaker.label"
    )
    segments: Mapped[list[TranscriptSegment]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", order_by="TranscriptSegment.idx"
    )


class Speaker(IdMixin, Base):
    __tablename__ = "speakers"

    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(120))
    talk_time_s: Mapped[float] = mapped_column(Float, default=0.0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)

    meeting: Mapped[Meeting] = relationship(back_populates="speakers")


class TranscriptSegment(IdMixin, Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (Index("ix_segments_meeting_idx", "meeting_id", "idx"),)

    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"))
    speaker_id: Mapped[str | None] = mapped_column(
        ForeignKey("speakers.id", ondelete="SET NULL"), nullable=True
    )
    idx: Mapped[int] = mapped_column(Integer)
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    meeting: Mapped[Meeting] = relationship(back_populates="segments")
    speaker: Mapped[Speaker | None] = relationship()


class TranscriptChunk(IdMixin, Base):
    """Retrieval unit for "Ask your meetings" (a window of consecutive segments)."""

    __tablename__ = "transcript_chunks"
    __table_args__ = (
        Index(
            "ix_transcript_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    speakers: Mapped[list[str]] = mapped_column(JSON, default=list)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(EmbeddingVector(get_settings().embedding_dim))
