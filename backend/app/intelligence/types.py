from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from app.schemas.insights import Insights


@dataclass(frozen=True)
class TranscriptLine:
    start: float
    end: float
    speaker: str
    text: str


@dataclass(frozen=True)
class AnalysisInput:
    title: str
    meeting_date: date
    lines: list[TranscriptLine]

    @property
    def duration_s(self) -> float:
        return max((ln.end for ln in self.lines), default=0.0)


@dataclass(frozen=True)
class LLMUsage:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    estimated: bool = False


@dataclass(frozen=True)
class ContextChunk:
    index: int  # 1-based citation number
    meeting_id: str
    meeting_title: str
    start_s: float
    end_s: float
    speakers: list[str]
    text: str
    score: float = 0.0


@dataclass
class AnalysisResult:
    insights: Insights
    usage: list[LLMUsage] = field(default_factory=list)


@dataclass
class AnswerResult:
    answer: str
    cited: list[int]
    usage: list[LLMUsage] = field(default_factory=list)


class InsightEngine(Protocol):
    name: str

    def analyze(self, data: AnalysisInput) -> AnalysisResult: ...

    def reduce(self, data: AnalysisInput, partials: list[Insights]) -> AnalysisResult: ...

    def answer(self, question: str, contexts: list[ContextChunk]) -> AnswerResult: ...


def fmt_ts(seconds: float) -> str:
    s = int(max(0, seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def render_transcript(lines: list[TranscriptLine]) -> str:
    return "\n".join(f"[{fmt_ts(ln.start)}] {ln.speaker}: {ln.text}" for ln in lines)
