"""Diarization error rate (DER) of the offline SpectralDiarizer on the demo meeting.

DER = (missed speech + false alarm + speaker confusion) / total reference speech, 10 ms frames,
no forgiveness collar, optimal speaker mapping by exhaustive search (few speakers).

    uv run --project backend python ml/scripts/eval_diarization.py
"""

from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.audio import read_wav, resample  # noqa: E402
from app.stt.diarizer import SpectralDiarizer  # noqa: E402

STEP = 0.01


def to_frames(turns: list[dict], n: int, names: dict[str, int]) -> np.ndarray:
    arr = np.full(n, -1, dtype=int)
    for t in turns:
        arr[int(t["start"] / STEP) : int(t["end"] / STEP)] = names.setdefault(t["speaker"], len(names))
    return arr


def der(ref: np.ndarray, hyp: np.ndarray) -> dict[str, float]:
    ref_ids = sorted(set(ref[ref >= 0]))
    hyp_ids = sorted(set(hyp[hyp >= 0]))
    total = float((ref >= 0).sum())
    missed = float(((ref >= 0) & (hyp < 0)).sum())
    fa = float(((ref < 0) & (hyp >= 0)).sum())
    both = (ref >= 0) & (hyp >= 0)
    best_correct = 0.0
    k = max(len(ref_ids), len(hyp_ids))
    for perm in itertools.permutations(range(k), len(hyp_ids)) if hyp_ids else [()]:
        mapping = dict(zip(hyp_ids, perm, strict=False))
        mapped = np.array([mapping.get(h, -2) for h in hyp[both]])
        best_correct = max(best_correct, float((mapped == ref[both]).sum()))
    confusion = float(both.sum()) - best_correct
    return {
        "der": (missed + fa + confusion) / total,
        "missed": missed / total,
        "false_alarm": fa / total,
        "confusion": confusion / total,
        "ref_speakers": len(ref_ids),
        "hyp_speakers": len(hyp_ids),
    }


def main() -> None:
    truth = json.loads((ROOT / "ml/data/demo_ground_truth.json").read_text())
    audio = resample(read_wav(ROOT / "backend/app/seed_data/demo_meeting.wav"), 16000)
    t0 = time.perf_counter()
    turns = SpectralDiarizer().diarize(audio)
    elapsed = time.perf_counter() - t0
    n = int(audio.duration_s / STEP) + 1
    ref = to_frames(truth["turns"], n, {})
    hyp = to_frames([{"start": t.start, "end": t.end, "speaker": t.speaker} for t in turns], n, {})
    result = der(ref, hyp) | {"runtime_s": round(elapsed, 3), "realtime_factor": round(elapsed / audio.duration_s, 4)}
    print(json.dumps({k: round(v, 4) if isinstance(v, float) else v for k, v in result.items()}, indent=2))


if __name__ == "__main__":
    main()
