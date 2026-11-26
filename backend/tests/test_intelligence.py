from __future__ import annotations

from datetime import date

import pytest

from app.embeddings.hashing import HashingEmbedder
from app.intelligence.dates import resolve_due
from app.intelligence.heuristic import HeuristicEngine
from app.intelligence.summarizer import chunk_lines, summarize
from app.intelligence.types import AnalysisInput, ContextChunk, TranscriptLine, fmt_ts
from app.services.pipeline import build_chunks

BASE = date(2026, 11, 26)  # Thursday


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("fix it by Friday", date(2026, 11, 27)),
        ("fix it by next Friday", date(2026, 12, 4)),
        ("send by Monday", date(2026, 11, 30)),
        ("by the end of the month", date(2026, 11, 30)),
        ("by end of week", date(2026, 11, 27)),
        ("tomorrow please", date(2026, 11, 27)),
        ("today", date(2026, 11, 26)),
        ("next week", date(2026, 11, 30)),
        ("within 3 days", date(2026, 11, 29)),
        ("in two weeks", date(2026, 12, 10)),
        ("by December 3rd", date(2026, 12, 3)),
        ("launch on September fifteenth", date(2027, 9, 15)),
        ("due 5 March", date(2027, 3, 5)),
        ("on February 30", None),
    ],
)
def test_resolve_due(text: str, expected: date | None) -> None:
    assert resolve_due(text, BASE)[0] == expected


def test_resolve_due_no_match() -> None:
    assert resolve_due("whenever", BASE) == (None, None, None)


def _lines(*rows: tuple[str, str]) -> list[TranscriptLine]:
    return [TranscriptLine(i * 5.0, i * 5.0 + 4.0, spk, text) for i, (spk, text) in enumerate(rows)]


def test_heuristic_extracts_actions_decisions_questions() -> None:
    lines = _lines(
        ("Ann", "Welcome to the roadmap review for the mobile release."),
        ("Bob", "Action item: migrate the billing database before launch."),
        ("Ann", "Carl will write the security review by tomorrow."),
        ("Bob", "We've decided to drop the legacy Android build entirely."),
        ("Ann", "Who owns the analytics dashboard?"),
        ("Bob", "No idea, we need to check with marketing."),
        ("Ann", "Is the beta stable?"),
        ("Bob", "Yes, it is stable now, great work, I am happy."),
        ("Ann", "I'm worried about the late design assets, that's a problem."),
        ("Bob", "I can do that."),
    )
    ins = HeuristicEngine().analyze(AnalysisInput("Roadmap", BASE, lines)).insights
    titles = {a.title: a for a in ins.action_items}
    assert "Migrate the billing database before launch" in titles
    assert titles["Write the security review"].owner == "Carl"
    assert titles["Write the security review"].due_date == date(2026, 11, 27)
    assert [d.text for d in ins.decisions] == [
        "We've decided to drop the legacy Android build entirely."
    ]
    assert [q.text for q in ins.open_questions] == ["Who owns the analytics dashboard?"]
    by = {s.speaker: s for s in ins.sentiment}
    assert by["Ann"].label == "negative" and by["Bob"].label == "positive"
    assert ins.executive_summary.startswith("2 participants")


def test_heuristic_empty_and_answer() -> None:
    engine = HeuristicEngine()
    empty = engine.analyze(AnalysisInput("x", BASE, [])).insights
    assert empty.executive_summary == "No speech was detected in this recording."
    ctx = [
        ContextChunk(
            1,
            "m",
            "Sync",
            65.0,
            80.0,
            ["Ann"],
            "Ann: The database migration is scheduled for Tuesday.",
        )
    ]
    ans = engine.answer("When is the database migration?", ctx)
    assert ans.cited == [1] and "01:05" in ans.answer


def test_map_reduce_dedupes_across_chunks() -> None:
    rows = []
    for i in range(80):
        if i == 10:
            rows.append(("Ann", "I will update the pricing page by Friday."))
        elif i == 50:
            rows.append(("Ann", "I will update the pricing page by Friday please."))
        elif i == 60:
            rows.append(("Bob", "We agreed to hire two more support engineers."))
        else:
            rows.append(
                (
                    "Bob" if i % 2 else "Ann",
                    f"Discussion point {i} about the quarterly roadmap planning.",
                )
            )
    lines = [TranscriptLine(i * 60.0, i * 60.0 + 50, s, t) for i, (s, t) in enumerate(rows)]
    result = summarize(
        HeuristicEngine(),
        AnalysisInput("All hands", BASE, lines),
        long_threshold_s=3600,
        chunk_s=600,
    )
    ins = result.insights
    assert (
        ins.strategy == "map_reduce" and ins.chunks_processed == len(chunk_lines(lines, 600)) == 8
    )
    assert [a.title for a in ins.action_items] == ["Update the pricing page"]
    assert len(ins.decisions) == 1
    assert len(result.usage) == 9
    short = summarize(
        HeuristicEngine(), AnalysisInput("x", BASE, lines[:3]), long_threshold_s=3600, chunk_s=600
    )
    assert short.insights.strategy == "single_pass"


def test_hashing_embedder_similarity() -> None:
    e = HashingEmbedder(64)
    a, b, c = e.embed(
        ["payment bugs in checkout", "the checkout payment bug", "marketing webinar schedule"]
    )
    dot = lambda x, y: sum(i * j for i, j in zip(x, y, strict=True))  # noqa: E731
    assert dot(a, b) > dot(a, c)
    assert abs(dot(a, a) - 1.0) < 1e-9
    assert e.embed_one("the and of") == [0.0] * 64


def test_build_chunks_and_fmt_ts() -> None:
    lines = [TranscriptLine(float(i), float(i) + 1, "A", "word " * 30) for i in range(5)]
    chunks = build_chunks(lines, target_words=60)
    assert len(chunks) == 4 and chunks[0][-1] == chunks[1][0]
    assert fmt_ts(3725) == "1:02:05" and fmt_ts(65) == "01:05"
