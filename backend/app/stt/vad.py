"""Adaptive energy-based voice-activity detection."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.stt.base import AudioData
from app.stt.features import HOP_S, frame_energy_db, frame_signal


@dataclass(frozen=True)
class SpeechRegion:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def detect_speech(
    audio: AudioData,
    *,
    min_speech_s: float = 0.25,
    min_silence_s: float = 0.30,
    pad_s: float = 0.05,
) -> list[SpeechRegion]:
    if audio.duration_s == 0:
        return []
    energy = frame_energy_db(frame_signal(audio.samples, audio.sample_rate))
    floor = float(np.percentile(energy, 10))
    loud = float(np.percentile(energy, 95))
    if loud - floor < 6.0:  # flat signal: all silence or all noise
        if loud < -50.0:
            return []
        return [SpeechRegion(0.0, audio.duration_s)]
    threshold = floor + 0.35 * (loud - floor)
    voiced = energy > threshold

    regions: list[list[float]] = []
    start: int | None = None
    for i, v in enumerate(voiced):
        if v and start is None:
            start = i
        elif not v and start is not None:
            regions.append([start * HOP_S, i * HOP_S])
            start = None
    if start is not None:
        regions.append([start * HOP_S, len(voiced) * HOP_S])

    merged: list[list[float]] = []
    for reg in regions:
        if merged and reg[0] - merged[-1][1] < min_silence_s:
            merged[-1][1] = reg[1]
        else:
            merged.append(reg)
    out = []
    for s, e in merged:
        if e - s >= min_speech_s:
            out.append(
                SpeechRegion(max(0.0, round(s - pad_s, 3)), min(audio.duration_s, round(e + pad_s, 3)))
            )
    return out
