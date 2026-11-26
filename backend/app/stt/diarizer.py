"""Offline speaker diarization: VAD -> fixed windows -> acoustic embeddings -> agglomerative clustering.

This is a deliberately small, deterministic baseline (no model downloads) that works well for
clean recordings with acoustically distinct voices. pyannote.audio is the production-grade
alternative (see ``pyannote_backend.py``) and is selected with ``DIARIZER_BACKEND=pyannote``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from app.stt.base import AudioData, SpeakerTurn
from app.stt.features import frame_energy_db, frame_pitch, frame_signal, log_mel
from app.stt.vad import SpeechRegion, detect_speech

Matrix = npt.NDArray[np.float64]
PITCH_SCALE = 80.0  # per unit of log-F0 (~3.5 semitones -> 16 units); calibrated, see docs/DECISIONS.md


@dataclass(frozen=True)
class Window:
    start: float
    end: float


def split_regions(regions: list[SpeechRegion], max_len: float = 2.0) -> list[Window]:
    windows: list[Window] = []
    for reg in regions:
        n = max(1, int(np.ceil(reg.duration / max_len)))
        step = reg.duration / n
        for i in range(n):
            windows.append(Window(reg.start + i * step, reg.start + (i + 1) * step))
    return windows


def embed_window(audio: AudioData, win: Window) -> npt.NDArray[np.float64] | None:
    sr = audio.sample_rate
    seg = audio.samples[int(win.start * sr) : int(win.end * sr)]
    if len(seg) < int(0.1 * sr):
        return None
    frames = frame_signal(seg, sr)
    energy = frame_energy_db(frames)
    keep = energy > (energy.max() - 30.0)  # drop near-silent frames inside the window
    if keep.sum() < 3:
        return None
    frames = frames[keep]
    mel = log_mel(frames, sr).astype(np.float64)
    mel -= mel.mean(axis=1, keepdims=True)  # remove per-frame loudness, keep spectral shape
    pitch = frame_pitch(frames, sr)
    voiced = pitch[pitch > 0]
    log_f0 = float(np.log(np.median(voiced))) if len(voiced) >= 3 else np.nan
    return np.concatenate([mel.mean(axis=0), mel.std(axis=0), [log_f0]])


def _standardize(feats: Matrix) -> Matrix:
    out = feats.copy()
    pitch = out[:, -1]
    if np.isnan(pitch).all():
        out[:, -1] = 0.0
    else:
        out[np.isnan(pitch), -1] = np.nanmedian(pitch)
    # Spectral features are z-scored (relative), but pitch is kept on an absolute log scale so
    # that the distance between two voices does not shrink as more speakers join the meeting.
    spec = out[:, :-1]
    out[:, :-1] = (spec - spec.mean(axis=0)) / (spec.std(axis=0) + 1e-6)
    out[:, -1] = (out[:, -1] - np.median(out[:, -1])) * PITCH_SCALE
    return out


def agglomerative(x: Matrix, threshold: float, max_clusters: int) -> list[int]:
    """Average-linkage clustering on (dim-normalised) Euclidean distance with Lance-Williams updates."""
    n = len(x)
    if n == 1:
        return [0]
    diff = x[:, None, :] - x[None, :, :]
    dist = np.sqrt((diff**2).sum(axis=-1)) / np.sqrt(x.shape[1])
    np.fill_diagonal(dist, np.inf)
    sizes = np.ones(n)
    active = np.ones(n, dtype=bool)
    members: dict[int, list[int]] = {i: [i] for i in range(n)}
    clusters = n
    while clusters > 1:
        masked = np.where(active[:, None] & active[None, :], dist, np.inf)
        flat = int(np.argmin(masked))
        i, j = divmod(flat, n)
        if masked[i, j] > threshold and clusters <= max_clusters:
            break
        # merge j into i
        new = (sizes[i] * dist[i] + sizes[j] * dist[j]) / (sizes[i] + sizes[j])
        dist[i, :] = new
        dist[:, i] = new
        dist[i, i] = np.inf
        sizes[i] += sizes[j]
        active[j] = False
        dist[j, :] = np.inf
        dist[:, j] = np.inf
        members[i].extend(members.pop(j))
        clusters -= 1
    labels = [0] * n
    for k, idxs in enumerate(sorted(members.values(), key=min)):
        for idx in idxs:
            labels[idx] = k
    return labels


def _reassign_short(labels: list[int], windows: list[Window], min_cluster_s: float) -> list[int]:
    """Fold clusters with very little total speech into their nearest-in-time neighbour."""
    totals: dict[int, float] = {}
    for lab, w in zip(labels, windows, strict=True):
        totals[lab] = totals.get(lab, 0.0) + (w.end - w.start)
    small = {lab for lab, t in totals.items() if t < min_cluster_s}
    if not small or len(small) == len(totals):
        return labels
    out = list(labels)
    for i, lab in enumerate(out):
        if lab in small:
            for d in range(1, len(out)):
                for j in (i - d, i + d):
                    if 0 <= j < len(out) and out[j] not in small:
                        out[i] = out[j]
                        break
                else:
                    continue
                break
    return out


def to_turns(
    labels: list[int], windows: list[Window], merge_gap_s: float = 1.0
) -> list[SpeakerTurn]:
    order: dict[int, int] = {}
    for lab in labels:
        order.setdefault(lab, len(order))
    turns: list[SpeakerTurn] = []
    for lab, w in zip(labels, windows, strict=True):
        name = f"SPEAKER_{order[lab]:02d}"
        if turns and turns[-1].speaker == name and w.start - turns[-1].end <= merge_gap_s:
            turns[-1].end = w.end
        else:
            turns.append(SpeakerTurn(round(w.start, 3), round(w.end, 3), name))
    return turns


class SpectralDiarizer:
    name = "spectral"

    def __init__(self, threshold: float = 2.2, max_speakers: int = 6) -> None:
        self.threshold = threshold
        self.max_speakers = max_speakers

    def diarize(self, audio: AudioData, audio_path: Path | None = None) -> list[SpeakerTurn]:
        regions = detect_speech(audio)
        windows = split_regions(regions)
        feats: list[npt.NDArray[np.float64]] = []
        kept: list[Window] = []
        for w in windows:
            emb = embed_window(audio, w)
            if emb is not None:
                feats.append(emb)
                kept.append(w)
        if not kept:
            return []
        if len(kept) == 1:
            return [SpeakerTurn(kept[0].start, kept[0].end, "SPEAKER_00")]
        x = _standardize(np.vstack(feats))
        labels = agglomerative(x, self.threshold, self.max_speakers)
        labels = _reassign_short(labels, kept, min_cluster_s=max(2.0, 0.03 * audio.duration_s))
        return to_turns(labels, kept)
