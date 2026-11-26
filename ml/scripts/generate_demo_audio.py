"""Generate the synthetic demo meeting (macOS `say` voices) plus its transcript fixture.

Outputs
- backend/app/seed_data/demo_meeting.wav           16 kHz mono PCM, ~70 s
- backend/app/fixtures/transcripts/<sha256>.json   timestamped text, *no* speaker labels
  (the stand-in for what Whisper would return; speakers come from the diarizer)
- ml/data/demo_ground_truth.json                    speaker turns + expected insights (for eval)

Run on macOS:  uv run --project backend python ml/scripts/generate_demo_audio.py
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RATE = 16000
VOICES = {"Priya": "Samantha", "Marcus": "Daniel", "Raj": "Ralph"}
SCRIPT: list[tuple[str, str]] = [
    ("Priya", "Good morning everyone. Let's get started with the Q3 launch planning sync. Our goal today is to lock the launch date and assign owners."),
    ("Marcus", "Thanks Priya. Engineering is on track. The mobile app beta passed QA yesterday, but we still have two open bugs in the payment flow."),
    ("Priya", "How long will the payment fixes take?"),
    ("Marcus", "About a week. I will fix the payment bugs by next Friday."),
    ("Raj", "From the marketing side, the campaign assets are ready. I am worried the press release depends on the final pricing."),
    ("Priya", "Good point. We decided to keep the pricing at twenty nine dollars per month for the launch."),
    ("Raj", "Great, that unblocks us. I will send the press release draft to the team by Wednesday."),
    ("Marcus", "One concern. Do we have enough support staff for launch week?"),
    ("Priya", "I am not sure yet. Let's revisit staffing next week. Marcus, can you update the release checklist by Monday?"),
    ("Marcus", "Yes, I can do that."),
    ("Priya", "So we agreed to launch on September fifteenth. Raj, please book the launch webinar by the end of the month."),
    ("Raj", "Will do. This is exciting, I think the team did a fantastic job."),
    ("Priya", "Agreed. Thanks everyone, great meeting."),
]
GAP_S = 0.55


def synth(voice: str, text: str, out: Path) -> np.ndarray:
    subprocess.run(
        ["say", "-v", voice, "-o", str(out), f"--data-format=LEI16@{RATE}", text],
        check=True,
    )
    with wave.open(str(out), "rb") as wf:
        data = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype(np.float32)
    return data / 32768.0


def trim(x: np.ndarray, thresh: float = 0.01) -> np.ndarray:
    idx = np.where(np.abs(x) > thresh)[0]
    return x if len(idx) == 0 else x[max(0, idx[0] - 160) : idx[-1] + 160]


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit("requires macOS `say`")
    rng = np.random.default_rng(7)
    pieces: list[np.ndarray] = [np.zeros(int(0.5 * RATE), dtype=np.float32)]
    t = 0.5
    segments, turns = [], []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (speaker, text) in enumerate(SCRIPT):
            audio = trim(synth(VOICES[speaker], text, Path(tmp) / f"{i}.wav"))
            start, end = t, t + len(audio) / RATE
            segments.append({"start": round(start, 2), "end": round(end, 2), "text": text})
            turns.append({"start": round(start, 2), "end": round(end, 2), "speaker": speaker})
            pieces += [audio, np.zeros(int(GAP_S * RATE), dtype=np.float32)]
            t = end + GAP_S
    signal = np.concatenate(pieces)
    signal += rng.normal(0, 0.002, size=len(signal)).astype(np.float32)  # faint room noise
    signal = np.clip(signal / np.max(np.abs(signal)) * 0.89, -1, 1)
    out_wav = ROOT / "backend/app/seed_data/demo_meeting.wav"
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes((signal * 32767).astype("<i2").tobytes())
    sha = hashlib.sha256(out_wav.read_bytes()).hexdigest()
    fixture_dir = ROOT / "backend/app/fixtures/transcripts"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    for old in fixture_dir.glob("*.json"):
        if json.loads(old.read_text()).get("name") == "demo_meeting":
            old.unlink()
    (fixture_dir / f"{sha}.json").write_text(
        json.dumps({"name": "demo_meeting", "language": "en", "segments": segments}, indent=2)
    )
    truth = {
        "audio_sha256": sha,
        "duration_s": round(len(signal) / RATE, 2),
        "turns": turns,
        "expected": {
            "action_items": [
                {"owner": "Marcus", "title": "fix the payment bugs", "due": "next Friday"},
                {"owner": "Raj", "title": "send the press release draft", "due": "Wednesday"},
                {"owner": "Marcus", "title": "update the release checklist", "due": "Monday"},
                {"owner": "Raj", "title": "book the launch webinar", "due": "end of the month"},
            ],
            "decisions": ["pricing at twenty nine dollars per month", "launch on September fifteenth"],
            "open_questions": ["enough support staff for launch week"],
        },
    }
    (ROOT / "ml/data/demo_ground_truth.json").write_text(json.dumps(truth, indent=2))
    print(f"wrote {out_wav} ({out_wav.stat().st_size / 1e6:.2f} MB, {truth['duration_s']} s) sha={sha[:12]}")


if __name__ == "__main__":
    main()
