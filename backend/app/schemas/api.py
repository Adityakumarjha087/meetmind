"""Request/response models for the HTTP API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl

from app.models.enums import ActionStatus, MeetingSource, MeetingStatus, PipelineStage, Role
from app.schemas.insights import Insights


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth
class RegisterIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str | None = None


class UserOut(ORM):
    id: str
    email: str
    name: str
    avatar_url: str | None = None
    has_password: bool = False
    google_connected: bool = False


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserOut


class GoogleAuthUrlOut(BaseModel):
    url: str


# ---------------------------------------------------------------- workspaces
class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    slack_webhook_url: HttpUrl | Literal[""] | None = None
    slack_auto_post: bool | None = None


class WorkspaceOut(ORM):
    id: str
    name: str
    role: Role
    slack_configured: bool = False
    slack_auto_post: bool = False
    member_count: int = 1
    created_at: datetime


class MemberOut(BaseModel):
    user_id: str
    email: str
    name: str
    role: Role


class MemberIn(BaseModel):
    email: EmailStr
    role: Role = Role.MEMBER


class MemberUpdate(BaseModel):
    role: Role


# ---------------------------------------------------------------- meetings
class SpeakerOut(ORM):
    id: str
    label: str
    display_name: str
    talk_time_s: float
    word_count: int


class SpeakerUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)


class SegmentOut(BaseModel):
    id: str
    idx: int
    start_s: float
    end_s: float
    text: str
    speaker_id: str | None
    speaker_name: str | None
    confidence: float | None = None


class MeetingSummaryOut(ORM):
    id: str
    workspace_id: str
    title: str
    source: MeetingSource
    status: MeetingStatus
    stage: PipelineStage
    progress: int
    status_message: str | None = None
    error: str | None = None
    duration_s: float | None = None
    scheduled_at: datetime | None = None
    created_at: datetime
    processing_started_at: datetime | None = None
    processing_finished_at: datetime | None = None
    attendees: list[str] = Field(default_factory=list)
    action_item_count: int = 0
    speaker_count: int = 0


class MeetingDetailOut(MeetingSummaryOut):
    original_filename: str | None = None
    audio_url: str | None = None
    waveform_peaks: list[float] | None = None
    stage_timings: dict[str, float] = Field(default_factory=dict)
    stt_backend: str | None = None
    diarizer_backend: str | None = None
    llm_provider: str | None = None
    insights: Insights | None = None
    speakers: list[SpeakerOut] = Field(default_factory=list)
    share_url: str | None = None


class MeetingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)


class MeetingPage(BaseModel):
    items: list[MeetingSummaryOut]
    total: int
    limit: int
    offset: int


class ProgressOut(BaseModel):
    meeting_id: str
    workspace_id: str
    status: MeetingStatus
    stage: PipelineStage
    progress: int
    message: str | None
    error: str | None


class ShareOut(BaseModel):
    share_token: str
    share_url: str


class PublicMeetingOut(BaseModel):
    title: str
    created_at: datetime
    scheduled_at: datetime | None
    duration_s: float | None
    insights: Insights | None
    action_items: list[dict[str, Any]]
    speakers: list[str]


# ---------------------------------------------------------------- action items
class ActionItemOut(ORM):
    id: str
    workspace_id: str
    meeting_id: str | None
    meeting_title: str | None = None
    title: str
    description: str | None
    owner_name: str | None
    assignee_id: str | None
    assignee_name: str | None = None
    due_date: date | None
    status: ActionStatus
    position: float
    source_start_s: float | None
    created_at: datetime
    updated_at: datetime


class ActionItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    owner_name: str | None = Field(default=None, max_length=120)
    assignee_id: str | None = None
    due_date: date | None = None
    status: ActionStatus = ActionStatus.TODO
    meeting_id: str | None = None


class ActionItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    owner_name: str | None = Field(default=None, max_length=120)
    assignee_id: str | None = None
    due_date: date | None = None
    status: ActionStatus | None = None
    position: float | None = None


# ---------------------------------------------------------------- RAG
class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    meeting_id: str | None = None


class CitationOut(BaseModel):
    index: int
    meeting_id: str
    meeting_title: str
    start_s: float
    end_s: float
    speakers: list[str]
    text: str
    score: float


class AskOut(BaseModel):
    answer: str
    citations: list[CitationOut]
    engine: str


class SearchHitOut(CitationOut):
    pass


# ---------------------------------------------------------------- integrations
class CalendarImportIn(BaseModel):
    days_ahead: int = Field(default=14, ge=1, le=90)


class CalendarImportOut(BaseModel):
    imported: int
    meetings: list[MeetingSummaryOut]


class IntegrationStatusOut(BaseModel):
    google_oauth_enabled: bool
    google_calendar_connected: bool
    slack_configured: bool
    llm_provider: str
    stt_backend: str
    diarizer_backend: str
    embedding_backend: str
