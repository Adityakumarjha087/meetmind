"""Audio normalisation (FFmpeg, with a pure-Python WAV fallback), loading and waveform peaks."""

from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

from app.core.config import get_settings
from app.core.logging import get_logger
from app.stt.base import AudioData, FloatArray

log = get_logger(__name__)


class AudioProcessingError(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return shutil.which(get_settings().ffmpeg_binary) is not None


def normalize_audio(src: Path, dst: Path, sample_rate: int | None = None) -> str:
    """Convert any audio/video input to 16 kHz mono PCM WAV with loudness normalisation.

    Returns the method used ("ffmpeg" or "python").
    """
    rate = sample_rate or get_settings().target_sample_rate
    dst.parent.mkdir(parents=True, exist_ok=True)
    if ffmpeg_available():
        cmd = [
            get_settings().ffmpeg_binary,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(rate),
            "-af",
            "highpass=f=60,loudnorm=I=-18:TP=-2:LRA=11",
            "-c:a",
            "pcm_s16le",
            str(dst),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, check=False)  # noqa: S603
        if proc.returncode != 0:
            raise AudioProcessingError(f"ffmpeg failed: {proc.stderr.strip()[:500]}")
        return "ffmpeg"
    # Fallback keeps tests/CI free of system dependencies; only WAV input is supported.
    audio = read_wav(src)
    audio = resample(audio, rate)
    write_wav(dst, peak_normalize(audio.samples), rate)
    return "python"


def read_wav(path: Path) -> AudioData:
    try:
        with wave.open(str(path), "rb") as wf:
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            rate = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
    except (wave.Error, EOFError) as exc:
        raise AudioProcessingError(
            "Unsupported audio format without FFmpeg (only PCM WAV can be decoded natively)"
        ) from exc
    if width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        ints = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
        ints = np.where(ints & 0x800000, ints - 0x1000000, ints)
        data = ints.astype(np.float32) / 8388608.0
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:  # pragma: no cover - exotic widths
        raise AudioProcessingError(f"Unsupported sample width: {width}")
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return AudioData(samples=data.astype(np.float32), sample_rate=rate)


def write_wav(path: Path, samples: FloatArray, sample_rate: int) -> None:
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def resample(audio: AudioData, rate: int) -> AudioData:
    if audio.sample_rate == rate or len(audio.samples) == 0:
        return AudioData(audio.samples, rate if len(audio.samples) == 0 else audio.sample_rate)
    duration = audio.duration_s
    n_out = int(round(duration * rate))
    x_old = np.linspace(0.0, duration, num=len(audio.samples), endpoint=False)
    x_new = np.linspace(0.0, duration, num=n_out, endpoint=False)
    out = np.interp(x_new, x_old, audio.samples).astype(np.float32)
    return AudioData(out, rate)


def peak_normalize(samples: FloatArray, target_dbfs: float = -1.0) -> FloatArray:
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    if peak < 1e-6:
        return samples
    gain = (10 ** (target_dbfs / 20.0)) / peak
    return (samples * gain).astype(np.float32)


def compute_peaks(samples: FloatArray, buckets: int = 800) -> list[float]:
    """Max-abs peaks per bucket for instant waveform rendering without client-side decoding."""
    if len(samples) == 0:
        return []
    buckets = max(1, min(buckets, len(samples)))
    edges = np.linspace(0, len(samples), buckets + 1, dtype=np.int64)
    peaks = np.maximum.reduceat(np.abs(samples), edges[:-1])
    top = float(peaks.max()) or 1.0
    return [round(float(p) / top, 4) for p in peaks]
