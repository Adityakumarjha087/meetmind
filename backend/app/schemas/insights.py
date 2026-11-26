"""Structured AI outputs for a meeting. Shared by every insight engine and the API."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class Decision(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    timestamp_s: float | None = None


class ActionItemDraft(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    owner: str | None = None
    due_date: date | None = None
    due_text: str | None = None
    timestamp_s: float | None = None


class OpenQuestion(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    timestamp_s: float | None = None


class SpeakerSentiment(BaseModel):
    speaker: str
    score: float = Field(ge=-1.0, le=1.0)
    label: Literal["positive", "neutral", "negative"]
    rationale: str | None = None
    talk_time_s: float = 0.0
    word_count: int = 0


class Insights(BaseModel):
    executive_summary: str
    key_points: list[str] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    action_items: list[ActionItemDraft] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    sentiment: list[SpeakerSentiment] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    strategy: Literal["single_pass", "map_reduce"] = "single_pass"
    chunks_processed: int = 1
    engine: str = "offline"
