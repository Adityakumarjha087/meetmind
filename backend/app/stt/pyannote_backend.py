"""pyannote.audio diarization. Optional: `uv sync --extra ml` and a HuggingFace token (HF_TOKEN)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.stt.base import AudioData, SpeakerTurn


class PyannoteDiarizer:
    name = "pyannote"

    def __init__(self, hf_token: str | None, max_speakers: int = 6) -> None:
        if not hf_token:
            raise RuntimeError("DIARIZER_BACKEND=pyannote requires HF_TOKEN")
        from pyannote.audio import Pipeline

        self._pipeline: Any = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", use_auth_token=hf_token
        )
        self.max_speakers = max_speakers

    def diarize(self, audio: AudioData, audio_path: Path) -> list[SpeakerTurn]:
        result = self._pipeline(str(audio_path), max_speakers=self.max_speakers)
        return [
            SpeakerTurn(float(turn.start), float(turn.end), str(label))
            for turn, _, label in result.itertracks(yield_label=True)
        ]
