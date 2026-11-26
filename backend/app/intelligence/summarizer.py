"""Single-pass vs map-reduce summarisation orchestration."""

from __future__ import annotations

from app.intelligence.types import AnalysisInput, AnalysisResult, InsightEngine, TranscriptLine


def chunk_lines(lines: list[TranscriptLine], chunk_s: float) -> list[list[TranscriptLine]]:
    """Split a transcript into time windows of ~chunk_s seconds, never splitting a line."""
    chunks: list[list[TranscriptLine]] = []
    current: list[TranscriptLine] = []
    window_start = lines[0].start if lines else 0.0
    for ln in lines:
        if current and ln.start - window_start >= chunk_s:
            chunks.append(current)
            current = []
            window_start = ln.start
        current.append(ln)
    if current:
        chunks.append(current)
    return chunks


def summarize(
    engine: InsightEngine,
    data: AnalysisInput,
    *,
    long_threshold_s: float,
    chunk_s: float,
) -> AnalysisResult:
    """Use map-reduce for recordings longer than ``long_threshold_s`` (default 1 hour).

    Map: analyse each ~10-minute window independently (bounded prompt size, parallelisable).
    Reduce: merge the partial notes into one coherent set for the whole meeting.
    """
    if data.duration_s <= long_threshold_s or len(data.lines) < 2:
        return engine.analyze(data)
    usage = []
    partials = []
    for chunk in chunk_lines(data.lines, chunk_s):
        part = engine.analyze(AnalysisInput(data.title, data.meeting_date, chunk))
        partials.append(part.insights)
        usage.extend(part.usage)
    reduced = engine.reduce(data, partials)
    reduced.usage = usage + reduced.usage
    return reduced
