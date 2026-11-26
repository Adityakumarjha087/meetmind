from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    VIEWER = "viewer"
    MEMBER = "member"
    ADMIN = "admin"
    OWNER = "owner"

    @property
    def rank(self) -> int:
        return ROLE_RANK[self]


ROLE_RANK: dict[Role, int] = {Role.VIEWER: 0, Role.MEMBER: 1, Role.ADMIN: 2, Role.OWNER: 3}


class MeetingStatus(StrEnum):
    SCHEDULED = "scheduled"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class MeetingSource(StrEnum):
    UPLOAD = "upload"
    RECORDING = "recording"
    CALENDAR = "calendar"
    SEED = "seed"


class PipelineStage(StrEnum):
    QUEUED = "queued"
    NORMALIZE = "normalize"
    TRANSCRIBE = "transcribe"
    DIARIZE = "diarize"
    MERGE = "merge"
    SUMMARIZE = "summarize"
    INDEX = "index"
    DONE = "done"
    FAILED = "failed"


class ActionStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class UsageKind(StrEnum):
    STT = "stt"
    DIARIZATION = "diarization"
    LLM = "llm"
    EMBEDDING = "embedding"
