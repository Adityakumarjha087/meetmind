"""LLM-backed insight engine: structured outputs + schema validation with one repair retry."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.core.logging import get_logger
from app.intelligence.types import (
    AnalysisInput,
    AnalysisResult,
    AnswerResult,
    ContextChunk,
    LLMUsage,
    fmt_ts,
    render_transcript,
)
from app.llm.base import ChatModel, Completion, LLMError
from app.schemas.insights import Insights, SpeakerSentiment

log = get_logger(__name__)

_NULLABLE_STR: dict[str, Any] = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_NULLABLE_NUM: dict[str, Any] = {"anyOf": [{"type": "number"}, {"type": "null"}]}


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


INSIGHTS_SCHEMA: dict[str, Any] = _obj(
    {
        "executive_summary": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "decisions": {
            "type": "array",
            "items": _obj({"text": {"type": "string"}, "timestamp_s": _NULLABLE_NUM}),
        },
        "action_items": {
            "type": "array",
            "items": _obj(
                {
                    "title": {"type": "string"},
                    "owner": _NULLABLE_STR,
                    "due_date": {
                        "anyOf": [
                            {
                                "type": "string",
                                "description": "ISO date YYYY-MM-DD resolved relative to the meeting date",
                            },
                            {"type": "null"},
                        ]
                    },
                    "due_text": _NULLABLE_STR,
                    "timestamp_s": _NULLABLE_NUM,
                }
            ),
        },
        "open_questions": {
            "type": "array",
            "items": _obj({"text": {"type": "string"}, "timestamp_s": _NULLABLE_NUM}),
        },
        "sentiment": {
            "type": "array",
            "items": _obj(
                {
                    "speaker": {"type": "string"},
                    "score": {"type": "number", "description": "-1 (negative) to 1 (positive)"},
                    "label": {"type": "string", "enum": ["positive", "neutral", "negative"]},
                    "rationale": _NULLABLE_STR,
                }
            ),
        },
        "topics": {"type": "array", "items": {"type": "string"}},
    }
)

ANSWER_SCHEMA: dict[str, Any] = _obj(
    {
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "integer"}},
    }
)

ANALYZE_SYSTEM = """You are MeetMind, an assistant that turns meeting transcripts into accurate, \
actionable notes. Use only information present in the transcript; never invent owners, dates or \
decisions. Each transcript line is "[mm:ss] Speaker: text".

Produce:
- executive_summary: 3-5 sentences a busy executive can read in 20 seconds.
- key_points: the most important discussion points.
- decisions: things the group explicitly agreed or decided.
- action_items: concrete commitments or requests. owner = the person responsible (a speaker label \
or a name mentioned in the transcript; null if unclear). Resolve relative due dates ("next Friday") \
to ISO dates using the meeting date; keep the original phrase in due_text.
- open_questions: questions raised but not resolved.
- sentiment: one entry per speaker label with score in [-1, 1].
- topics: 3-6 short topic labels.
timestamp_s is the start time in seconds of the line where the item appears."""

REDUCE_SYSTEM = """You are MeetMind. You receive structured notes extracted from consecutive \
sections of one long meeting. Merge them into a single set of notes for the whole meeting: write a \
fresh executive summary covering the full arc of the meeting, de-duplicate decisions, action items \
and questions (keep the earliest timestamp), drop questions that a later section resolved, and \
produce one sentiment entry per speaker."""

ANSWER_SYSTEM = """You answer questions about a team's past meetings using ONLY the numbered \
transcript excerpts provided. Cite every claim with the excerpt number in square brackets, e.g. [2]. \
If the excerpts do not contain the answer, say so plainly. Return the list of excerpt numbers you \
cited in `citations`."""


class LLMEngine:
    def __init__(self, model: ChatModel, max_tokens: int = 16000) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.name = f"{model.provider}:{model.model}"

    def _call_json(
        self, system: str, prompt: str, schema: dict[str, Any]
    ) -> tuple[dict[str, Any], list[Completion]]:
        calls: list[Completion] = []
        last_error = ""
        for attempt in range(2):
            p = (
                prompt
                if attempt == 0
                else (
                    f"{prompt}\n\nYour previous reply was invalid ({last_error}). Reply with JSON only."
                )
            )
            completion = self.model.complete(
                system=system, prompt=p, json_schema=schema, max_tokens=self.max_tokens
            )
            calls.append(completion)
            try:
                data = json.loads(_strip_fences(completion.text))
                if isinstance(data, dict):
                    return data, calls
                last_error = "top-level value must be an object"
            except json.JSONDecodeError as exc:
                last_error = f"JSON decode error: {exc.msg}"
            log.warning("llm_invalid_json", attempt=attempt, provider=self.model.provider)
        raise LLMError(f"model returned invalid JSON twice: {last_error}")

    def _validate(self, raw: dict[str, Any], data: AnalysisInput) -> Insights:
        try:
            insights = Insights.model_validate({**raw, "engine": self.name})
        except ValidationError as exc:
            # Drop malformed list items rather than failing the whole meeting.
            cleaned = dict(raw)
            for key in ("decisions", "action_items", "open_questions", "sentiment"):
                items = []
                for item in raw.get(key, []) or []:
                    try:
                        Insights.model_validate({"executive_summary": "x", key: [item]})
                        items.append(item)
                    except ValidationError:
                        continue
                cleaned[key] = items
            try:
                insights = Insights.model_validate({**cleaned, "engine": self.name})
            except ValidationError:
                raise LLMError(f"model output failed validation: {exc.errors()[:3]}") from exc
        return _attach_talk_time(insights, data)

    def _prompt(self, data: AnalysisInput) -> str:
        return (
            f"Meeting title: {data.title}\nMeeting date: {data.meeting_date.isoformat()}\n"
            f"Duration: {fmt_ts(data.duration_s)}\n\nTranscript:\n{render_transcript(data.lines)}"
        )

    def analyze(self, data: AnalysisInput) -> AnalysisResult:
        raw, calls = self._call_json(ANALYZE_SYSTEM, self._prompt(data), INSIGHTS_SCHEMA)
        return AnalysisResult(self._validate(raw, data), [_usage(c) for c in calls])

    def reduce(self, data: AnalysisInput, partials: list[Insights]) -> AnalysisResult:
        sections = "\n\n".join(
            f"## Section {i + 1}\n"
            + p.model_dump_json(exclude={"strategy", "chunks_processed", "engine"})
            for i, p in enumerate(partials)
        )
        prompt = (
            f"Meeting title: {data.title}\nMeeting date: {data.meeting_date.isoformat()}\n"
            f"Duration: {fmt_ts(data.duration_s)}\n\n{sections}"
        )
        raw, calls = self._call_json(REDUCE_SYSTEM, prompt, INSIGHTS_SCHEMA)
        insights = self._validate(raw, data).model_copy(
            update={"strategy": "map_reduce", "chunks_processed": len(partials)}
        )
        return AnalysisResult(insights, [_usage(c) for c in calls])

    def answer(self, question: str, contexts: list[ContextChunk]) -> AnswerResult:
        if not contexts:
            return AnswerResult("I couldn't find anything about that in your meetings.", [])
        excerpts = "\n\n".join(
            f'[{c.index}] Meeting "{c.meeting_title}" at {fmt_ts(c.start_s)}-{fmt_ts(c.end_s)} '
            f"({', '.join(c.speakers)}):\n{c.text}"
            for c in contexts
        )
        raw, calls = self._call_json(
            ANSWER_SYSTEM, f"Excerpts:\n{excerpts}\n\nQuestion: {question}", ANSWER_SCHEMA
        )
        valid = {c.index for c in contexts}
        cited = sorted(
            {int(i) for i in raw.get("citations", []) if isinstance(i, int) and i in valid}
        )
        return AnswerResult(str(raw.get("answer", "")).strip(), cited, [_usage(c) for c in calls])


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    return t.strip()


def _usage(c: Completion) -> LLMUsage:
    return LLMUsage(c.provider, c.model, c.input_tokens, c.output_tokens, c.latency_ms)


def _attach_talk_time(insights: Insights, data: AnalysisInput) -> Insights:
    talk: dict[str, float] = {}
    wc: dict[str, int] = {}
    for ln in data.lines:
        talk[ln.speaker] = talk.get(ln.speaker, 0.0) + max(0.0, ln.end - ln.start)
        wc[ln.speaker] = wc.get(ln.speaker, 0) + len(ln.text.split())
    by_name = {s.speaker: s for s in insights.sentiment}
    merged: list[SpeakerSentiment] = []
    for speaker in sorted(talk, key=lambda sp: -talk[sp]):
        base = by_name.get(speaker) or SpeakerSentiment(speaker=speaker, score=0.0, label="neutral")
        merged.append(
            base.model_copy(
                update={"talk_time_s": round(talk[speaker], 2), "word_count": wc[speaker]}
            )
        )
    return insights.model_copy(update={"sentiment": merged})
