"""Speech pipeline primitives and the pluggable backend protocols."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float32]


@dataclass(frozen=True)
class AudioData:
    samples: FloatArray  # mono, float32 in [-1, 1]
    sample_rate: int

    @property
    def duration_s(self) -> float:
        return float(len(self.samples)) / float(self.sample_rate) if self.sample_rate else 0.0


@dataclass
class TranscriptPiece:
    start: float
    end: float
    text: str
    confidence: float | None = None
    speaker_hint: str | None = None


@dataclass
class SpeakerTurn:
    start: float
    end: float
    speaker: str


@dataclass
class LabelledSegment:
    start: float
    end: float
    text: str
    speaker: str
    confidence: float | None = None


@dataclass
class TranscriptionContext:
    """Everything a transcriber may use: the normalised audio plus optional sidecar transcript."""

    audio_path: Path
    audio: AudioData
    original_sha256: str | None = None
    sidecar_text: str | None = None
    sidecar_filename: str | None = None
    language: str | None = None
    extras: dict[str, str] = field(default_factory=dict)


class Transcriber(Protocol):
    name: str

    def transcribe(self, ctx: TranscriptionContext) -> list[TranscriptPiece]: ...


class Diarizer(Protocol):
    name: str

    def diarize(self, audio: AudioData, audio_path: Path) -> list[SpeakerTurn]: ...
