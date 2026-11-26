"""Merge transcriber output with diarization turns into a speaker-labelled transcript."""

from __future__ import annotations

from collections import Counter, defaultdict

from app.stt.base import LabelledSegment, SpeakerTurn, TranscriptPiece


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def assign_speakers(
    pieces: list[TranscriptPiece], turns: list[SpeakerTurn]
) -> list[LabelledSegment]:
    """Label each transcript piece with the diarization speaker it overlaps most.

    Pieces with no overlapping turn inherit the temporally nearest turn's speaker. When
    diarization produced nothing, everything is attributed to a single speaker.
    """
    out: list[LabelledSegment] = []
    for piece in sorted(pieces, key=lambda p: p.start):
        if not turns:
            speaker = "SPEAKER_00"
        else:
            scores: dict[str, float] = defaultdict(float)
            for t in turns:
                ov = _overlap(piece.start, piece.end, t.start, t.end)
                if ov > 0:
                    scores[t.speaker] += ov
            if scores:
                speaker = max(scores.items(), key=lambda kv: (kv[1], -int(kv[0][-2:])))[0]
            else:
                mid = (piece.start + piece.end) / 2
                nearest = min(turns, key=lambda t: min(abs(t.start - mid), abs(t.end - mid)))
                speaker = nearest.speaker
        out.append(LabelledSegment(piece.start, piece.end, piece.text, speaker, piece.confidence))
    return out


def speaker_name_hints(
    pieces: list[TranscriptPiece], segments: list[LabelledSegment]
) -> dict[str, str]:
    """If the sidecar transcript carried speaker names, map diarized labels to them by majority vote."""
    votes: dict[str, Counter[str]] = defaultdict(Counter)
    ordered = sorted(pieces, key=lambda p: p.start)
    for piece, seg in zip(ordered, segments, strict=True):
        if piece.speaker_hint:
            votes[seg.speaker][piece.speaker_hint] += max(1, len(piece.text.split()))
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for label, counter in sorted(votes.items(), key=lambda kv: -sum(kv[1].values())):
        for name, _ in counter.most_common():
            if name not in used:
                mapping[label] = name
                used.add(name)
                break
    return mapping
