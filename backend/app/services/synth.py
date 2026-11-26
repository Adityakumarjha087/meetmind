"""Deterministic 'voice-like' synthetic audio for demos and tests (no TTS, no downloads).

Each speaker gets a distinct fundamental frequency and harmonic profile, amplitude-modulated at
syllable rate, so the offline diarizer can separate them just like real voices with distinct pitch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from app.services.audio import write_wav

VOICE_F0 = [118.0, 205.0, 160.0, 250.0, 95.0, 140.0]
HARMONIC_PROFILES = [
    [1.0, 0.6, 0.35, 0.2, 0.1],
    [1.0, 0.3, 0.5, 0.15, 0.25],
    [1.0, 0.8, 0.2, 0.3, 0.05],
    [1.0, 0.4, 0.4, 0.4, 0.1],
    [1.0, 0.7, 0.5, 0.1, 0.2],
    [1.0, 0.2, 0.6, 0.2, 0.3],
]


def synthesize(segments: list[dict[str, Any]], path: Path, sample_rate: int = 16000, seed: int = 0) -> float:
    rng = np.random.default_rng(seed)
    speakers: dict[str, int] = {}
    for seg in segments:
        speakers.setdefault(str(seg.get("speaker", "A")), len(speakers))
    total = max(float(s["end"]) for s in segments) + 1.0
    out = rng.normal(0, 0.003, int(total * sample_rate)).astype(np.float32)
    for seg in segments:
        idx = speakers[str(seg.get("speaker", "A"))] % len(VOICE_F0)
        start, end = int(float(seg["start"]) * sample_rate), int(float(seg["end"]) * sample_rate)
        t = np.arange(end - start) / sample_rate
        f0 = VOICE_F0[idx] * (1 + 0.03 * np.sin(2 * np.pi * 0.7 * t + rng.uniform(0, 6)))
        phase = 2 * np.pi * np.cumsum(f0) / sample_rate
        wave = sum(w * np.sin((k + 1) * phase) for k, w in enumerate(HARMONIC_PROFILES[idx]))
        syllables = 0.55 + 0.45 * np.clip(np.sin(2 * np.pi * 4.0 * t + rng.uniform(0, 6)), 0, None)
        ramp = np.minimum(1.0, np.minimum(t, t[-1] - t) / 0.03)
        out[start:end] += (0.25 * wave * syllables * ramp).astype(np.float32)
    write_wav(path, out / max(1e-6, float(np.max(np.abs(out)))) * 0.9, sample_rate)
    return total
