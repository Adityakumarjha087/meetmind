"""Offline transcriber: uses a sidecar transcript (JSON / SRT / VTT / TXT) or a hash-keyed fixture.

This is the default STT backend so that the full pipeline, tests and CI run with zero model
downloads or API keys. Uploads that ship without any transcript get VAD-derived placeholder
segments (clearly marked) - switch ``STT_BACKEND=faster_whisper`` for real speech recognition.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.stt.base import TranscriptionContext, TranscriptPiece
from app.stt.vad import detect_speech

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "transcripts"
_TS = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
_VOICE = re.compile(r"^<v\s+([^>]+)>(.*?)(?:</v>)?$")
_SPEAKER_PREFIX = re.compile(r"^([A-Z][\w .'-]{0,40}):\s+(.*)$")


class TranscriptParseError(ValueError):
    pass


def _ts(value: str) -> float:
    m = _TS.search(value)
    if not m:
        raise TranscriptParseError(f"bad timestamp: {value!r}")
    h, mnt, s, ms = m.groups()
    return int(h or 0) * 3600 + int(mnt) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def _split_speaker(text: str) -> tuple[str | None, str]:
    vm = _VOICE.match(text)
    if vm:
        return vm.group(1).strip(), vm.group(2).strip()
    pm = _SPEAKER_PREFIX.match(text)
    if pm and len(pm.group(1).split()) <= 3:
        return pm.group(1).strip(), pm.group(2).strip()
    return None, text


def parse_json(raw: str) -> list[TranscriptPiece]:
    data = json.loads(raw)
    segments = data.get("segments", data) if isinstance(data, dict) else data
    if not isinstance(segments, list):
        raise TranscriptParseError("JSON transcript must be a list or have a 'segments' list")
    out: list[TranscriptPiece] = []
    for seg in segments:
        try:
            text = str(seg["text"]).strip()
            start, end = float(seg["start"]), float(seg["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TranscriptParseError(f"invalid segment: {seg!r}") from exc
        if text and end >= start:
            hint = seg.get("speaker")
            out.append(TranscriptPiece(start, end, text, seg.get("confidence"), hint))
    return out


def parse_cues(raw: str) -> list[TranscriptPiece]:
    """Parse SRT or WebVTT cue blocks."""
    out: list[TranscriptPiece] = []
    blocks = re.split(r"\r?\n\s*\r?\n", raw.strip())
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        timing_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if timing_idx is None:
            continue
        left, right = lines[timing_idx].split("-->", 1)
        text = " ".join(lines[timing_idx + 1 :]).strip()
        if not text:
            continue
        speaker, text = _split_speaker(text)
        out.append(TranscriptPiece(_ts(left), _ts(right.split()[0]), text, None, speaker))
    if not out:
        raise TranscriptParseError("no cues found")
    return out


def parse_plain(raw: str, ctx: TranscriptionContext) -> list[TranscriptPiece]:
    """Plain text without timings: spread lines over detected speech proportionally to length."""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return []
    regions = detect_speech(ctx.audio)
    start = regions[0].start if regions else 0.0
    end = regions[-1].end if regions else max(ctx.audio.duration_s, float(len(lines)))
    weights = [max(1, len(ln.split())) for ln in lines]
    total = float(sum(weights))
    out: list[TranscriptPiece] = []
    cursor = start
    for ln, w in zip(lines, weights, strict=True):
        span = (end - start) * w / total
        speaker, text = _split_speaker(ln)
        out.append(TranscriptPiece(round(cursor, 3), round(cursor + span, 3), text, None, speaker))
        cursor += span
    return out


def parse_transcript(
    raw: str, filename: str | None, ctx: TranscriptionContext
) -> list[TranscriptPiece]:
    name = (filename or "").lower()
    stripped = raw.lstrip()
    if name.endswith(".json") or stripped.startswith(("{", "[")):
        return parse_json(raw)
    if name.endswith((".srt", ".vtt")) or stripped.startswith("WEBVTT") or "-->" in raw:
        return parse_cues(raw)
    return parse_plain(raw, ctx)


def placeholder_from_vad(ctx: TranscriptionContext) -> list[TranscriptPiece]:
    return [
        TranscriptPiece(
            r.start,
            r.end,
            "[speech - transcript unavailable with the offline STT backend]",
            0.0,
        )
        for r in detect_speech(ctx.audio)
    ]


class SidecarTranscriber:
    name = "sidecar"

    def __init__(self, fixture_dir: Path = FIXTURE_DIR) -> None:
        self.fixture_dir = fixture_dir

    def transcribe(self, ctx: TranscriptionContext) -> list[TranscriptPiece]:
        if ctx.sidecar_text:
            return parse_transcript(ctx.sidecar_text, ctx.sidecar_filename, ctx)
        if ctx.original_sha256:
            fixture = self.fixture_dir / f"{ctx.original_sha256}.json"
            if fixture.is_file():
                return parse_json(fixture.read_text(encoding="utf-8"))
        return placeholder_from_vad(ctx)
