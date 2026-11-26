from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from app.services import audio as audio_mod
from app.services.audio import (
    AudioProcessingError,
    compute_peaks,
    normalize_audio,
    peak_normalize,
    read_wav,
    resample,
    write_wav,
)
from app.services.synth import synthesize
from app.stt.base import AudioData, SpeakerTurn, TranscriptionContext, TranscriptPiece
from app.stt.diarizer import SpectralDiarizer, agglomerative
from app.stt.merge import assign_speakers, speaker_name_hints
from app.stt.openai_whisper import OpenAIWhisperTranscriber
from app.stt.sidecar import (
    SidecarTranscriber,
    TranscriptParseError,
    parse_cues,
    parse_json,
    parse_transcript,
)
from app.stt.vad import detect_speech
from tests.conftest import DEMO_WAV


def _ctx(audio: AudioData, path: Path, **kw: Any) -> TranscriptionContext:
    return TranscriptionContext(audio_path=path, audio=audio, **kw)


@pytest.fixture
def two_speaker(tmp_path: Path) -> tuple[AudioData, Path, list[dict[str, Any]]]:
    segs = [
        {"start": 0.5, "end": 3.0, "speaker": "A", "text": "x"},
        {"start": 3.6, "end": 6.0, "speaker": "B", "text": "y"},
        {"start": 6.6, "end": 9.0, "speaker": "A", "text": "z"},
        {"start": 9.6, "end": 12.0, "speaker": "B", "text": "w"},
    ]
    path = tmp_path / "two.wav"
    synthesize(segs, path)
    return read_wav(path), path, segs


def test_wav_roundtrip_resample_and_peaks(tmp_path: Path) -> None:
    sr = 8000
    t = np.arange(sr) / sr
    tone = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    p = tmp_path / "t.wav"
    write_wav(p, tone, sr)
    a = read_wav(p)
    assert a.sample_rate == sr and abs(a.duration_s - 1.0) < 1e-3
    up = resample(a, 16000)
    assert up.sample_rate == 16000 and len(up.samples) == 16000
    assert abs(float(np.max(np.abs(peak_normalize(a.samples)))) - 10 ** (-1 / 20)) < 1e-3
    peaks = compute_peaks(a.samples, 50)
    assert len(peaks) == 50 and max(peaks) == 1.0
    assert compute_peaks(np.zeros(0, dtype=np.float32)) == []
    assert peak_normalize(np.zeros(10, dtype=np.float32)).sum() == 0


def test_read_wav_stereo_8bit_and_garbage(tmp_path: Path) -> None:
    import wave

    p = tmp_path / "s.wav"
    with wave.open(str(p), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(1)
        wf.setframerate(8000)
        wf.writeframes(bytes([128, 255] * 800))
    a = read_wav(p)
    assert len(a.samples) == 800 and a.samples.max() < 0.6
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not a wav")
    with pytest.raises(AudioProcessingError):
        read_wav(bad)


def test_normalize_python_fallback(tmp_path: Path) -> None:
    out = tmp_path / "n.wav"
    assert normalize_audio(DEMO_WAV, out, 16000) == "python"
    assert read_wav(out).sample_rate == 16000


def test_normalize_uses_ffmpeg_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kw: Any) -> SimpleNamespace:
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(audio_mod, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert normalize_audio(tmp_path / "in.mp4", tmp_path / "o.wav") == "ffmpeg"
    cmd = calls[0]
    assert "-ac" in cmd and cmd[cmd.index("-ar") + 1] == "16000" and "-vn" in cmd
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kw: SimpleNamespace(returncode=1, stderr="boom")
    )
    with pytest.raises(AudioProcessingError, match="boom"):
        normalize_audio(tmp_path / "in.mp4", tmp_path / "o.wav")


def test_vad_detects_regions(two_speaker: tuple[AudioData, Path, list[dict[str, Any]]]) -> None:
    audio, _, segs = two_speaker
    regions = detect_speech(audio)
    assert len(regions) == 4
    for r, s in zip(regions, segs, strict=True):
        assert abs(r.start - s["start"]) < 0.15 and abs(r.end - s["end"]) < 0.15
    silent = AudioData(np.zeros(16000, dtype=np.float32), 16000)
    assert detect_speech(silent) == []
    assert detect_speech(AudioData(np.zeros(0, dtype=np.float32), 16000)) == []


def test_diarizer_separates_two_voices(
    two_speaker: tuple[AudioData, Path, list[dict[str, Any]]],
) -> None:
    audio, path, _ = two_speaker
    turns = SpectralDiarizer().diarize(audio, path)
    assert [t.speaker for t in turns] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00", "SPEAKER_01"]
    assert SpectralDiarizer().diarize(AudioData(np.zeros(16000, dtype=np.float32), 16000)) == []


def test_agglomerative_respects_max_clusters() -> None:
    x = np.array([[0.0], [0.1], [5.0], [5.1], [10.0]])
    assert len(set(agglomerative(x, threshold=0.5, max_clusters=10))) == 3
    assert len(set(agglomerative(x, threshold=0.0, max_clusters=2))) == 2
    assert agglomerative(np.array([[1.0]]), 1.0, 3) == [0]


def test_merge_assigns_by_overlap_and_hints() -> None:
    pieces = [
        TranscriptPiece(0.0, 2.0, "hello there", speaker_hint="Ann"),
        TranscriptPiece(2.1, 4.0, "hi ann", speaker_hint="Bob"),
        TranscriptPiece(10.0, 11.0, "late line"),
    ]
    turns = [SpeakerTurn(0.0, 2.05, "SPEAKER_00"), SpeakerTurn(2.05, 4.5, "SPEAKER_01")]
    labelled = assign_speakers(pieces, turns)
    assert [s.speaker for s in labelled] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_01"]
    assert speaker_name_hints(pieces, labelled) == {"SPEAKER_00": "Ann", "SPEAKER_01": "Bob"}
    assert {s.speaker for s in assign_speakers(pieces, [])} == {"SPEAKER_00"}


def test_sidecar_parsers(tmp_path: Path) -> None:
    audio = read_wav(DEMO_WAV)
    ctx = _ctx(audio, DEMO_WAV)
    srt = "1\n00:00:01,000 --> 00:00:03,500\nAlice: Hello team\n\n2\n00:00:04,000 --> 00:00:06,000\nWe should ship.\n"
    out = parse_transcript(srt, "a.srt", ctx)
    assert out[0].speaker_hint == "Alice" and out[0].text == "Hello team" and out[1].start == 4.0
    vtt = "WEBVTT\n\n00:01.000 --> 00:02.000\n<v Bob>Hey</v>\n"
    assert parse_cues(vtt)[0].speaker_hint == "Bob"
    js = json.dumps([{"start": 0, "end": 1, "text": "a", "speaker": "Z"}])
    assert parse_json(js)[0].speaker_hint == "Z"
    plain = parse_transcript(
        "Carol: first line here\nsecond line is a bit longer than first\n", "notes.txt", ctx
    )
    assert len(plain) == 2 and plain[0].speaker_hint == "Carol" and plain[1].start > plain[0].start
    with pytest.raises(TranscriptParseError):
        parse_json(json.dumps({"segments": [{"start": "x"}]}))
    with pytest.raises(TranscriptParseError):
        parse_cues("WEBVTT\n\nno cues here")
    with pytest.raises(TranscriptParseError):
        parse_json('{"segments": 5}')


def test_sidecar_transcriber_fixture_and_placeholder(
    two_speaker: tuple[AudioData, Path, list[dict[str, Any]]],
) -> None:
    import hashlib

    t = SidecarTranscriber()
    demo = read_wav(DEMO_WAV)
    sha = hashlib.sha256(DEMO_WAV.read_bytes()).hexdigest()
    assert len(t.transcribe(_ctx(demo, DEMO_WAV, original_sha256=sha))) == 13
    audio, path, _ = two_speaker
    placeholder = t.transcribe(_ctx(audio, path, original_sha256="0" * 64))
    assert len(placeholder) == 4 and "unavailable" in placeholder[0].text


def test_openai_whisper_transcriber(tmp_path: Path) -> None:
    class FakeTranscriptions:
        def create(self, **kw: Any) -> SimpleNamespace:
            assert kw["response_format"] == "verbose_json"
            return SimpleNamespace(
                segments=[
                    SimpleNamespace(start=0.0, end=1.5, text=" Hi "),
                    {"start": 2, "end": 3, "text": ""},
                ]
            )

    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=FakeTranscriptions()))
    out = OpenAIWhisperTranscriber(client).transcribe(_ctx(read_wav(DEMO_WAV), DEMO_WAV))
    assert [(p.start, p.text) for p in out] == [(0.0, "Hi")]
