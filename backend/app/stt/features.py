"""Lightweight, dependency-free acoustic features (framing, log-mel energies, autocorrelation pitch)."""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import numpy.typing as npt

from app.stt.base import FloatArray

FRAME_S = 0.025
HOP_S = 0.010


def frame_signal(samples: FloatArray, sample_rate: int) -> FloatArray:
    frame = int(FRAME_S * sample_rate)
    hop = int(HOP_S * sample_rate)
    if len(samples) < frame:
        samples = np.pad(samples, (0, frame - len(samples)))
    n = 1 + (len(samples) - frame) // hop
    idx = np.arange(frame)[None, :] + hop * np.arange(n)[:, None]
    frames: FloatArray = samples[idx].astype(np.float32)
    return frames


def frame_energy_db(frames: FloatArray) -> FloatArray:
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-12)
    out: FloatArray = (20.0 * np.log10(rms + 1e-9)).astype(np.float32)
    return out


@lru_cache(maxsize=8)
def mel_filterbank(
    sample_rate: int, n_fft: int, n_mels: int, fmin: float, fmax: float
) -> npt.NDArray[np.float64]:
    def hz_to_mel(f: npt.ArrayLike) -> npt.NDArray[np.float64]:
        return 2595.0 * np.log10(1.0 + np.asarray(f, dtype=np.float64) / 700.0)

    def mel_to_hz(m: npt.ArrayLike) -> npt.NDArray[np.float64]:
        return 700.0 * (10 ** (np.asarray(m, dtype=np.float64) / 2595.0) - 1.0)

    mels = np.linspace(hz_to_mel(fmin), hz_to_mel(fmax), n_mels + 2)
    hz = mel_to_hz(mels)
    bins = np.floor((n_fft + 1) * hz / sample_rate).astype(int)
    fb = np.zeros((n_mels, n_fft // 2 + 1))
    for m in range(1, n_mels + 1):
        left, center, right = bins[m - 1], bins[m], bins[m + 1]
        center = max(center, left + 1)
        right = max(right, center + 1)
        fb[m - 1, left:center] = (np.arange(left, center) - left) / (center - left)
        fb[m - 1, center:right] = (right - np.arange(center, right)) / (right - center)
    return fb


def log_mel(frames: FloatArray, sample_rate: int, n_mels: int = 24) -> FloatArray:
    n_fft = 512
    window = np.hanning(frames.shape[1])
    spec = np.abs(np.fft.rfft(frames * window, n=n_fft, axis=1)) ** 2
    fb = mel_filterbank(sample_rate, n_fft, n_mels, 60.0, min(7600.0, sample_rate / 2 - 100))
    out: FloatArray = np.log(spec @ fb.T + 1e-8).astype(np.float32)
    return out


def frame_pitch(
    frames: FloatArray, sample_rate: int, fmin: float = 70.0, fmax: float = 400.0
) -> FloatArray:
    """Autocorrelation F0 per frame (0 where unvoiced). Vectorised via FFT."""
    n = frames.shape[1]
    x = frames - frames.mean(axis=1, keepdims=True)
    spec = np.fft.rfft(x, n=2 * n, axis=1)
    ac = np.fft.irfft(np.abs(spec) ** 2, axis=1)[:, :n]
    lag_min = int(sample_rate / fmax)
    lag_max = min(int(sample_rate / fmin), n - 1)
    if lag_max <= lag_min:
        return np.zeros(len(frames), dtype=np.float32)
    region = ac[:, lag_min:lag_max]
    best = np.argmax(region, axis=1)
    peak = region[np.arange(len(region)), best]
    voiced = peak > 0.35 * (ac[:, 0] + 1e-9)
    f0 = sample_rate / (best + lag_min)
    out: FloatArray = np.where(voiced, f0, 0.0).astype(np.float32)
    return out
