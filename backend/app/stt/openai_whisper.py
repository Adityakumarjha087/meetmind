"""Hosted Whisper via the official OpenAI SDK (verbose_json segments)."""

from __future__ import annotations

from typing import Any

from app.stt.base import TranscriptionContext, TranscriptPiece


class OpenAIWhisperTranscriber:
    name = "openai_whisper"

    def __init__(self, client: Any, model: str = "whisper-1") -> None:
        self._client = client
        self.model = model

    def transcribe(self, ctx: TranscriptionContext) -> list[TranscriptPiece]:
        with ctx.audio_path.open("rb") as fh:
            result = self._client.audio.transcriptions.create(
                model=self.model,
                file=fh,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
        segments = getattr(result, "segments", None) or []
        out: list[TranscriptPiece] = []
        for seg in segments:
            text = (seg.text if hasattr(seg, "text") else seg["text"]).strip()
            start = float(seg.start if hasattr(seg, "start") else seg["start"])
            end = float(seg.end if hasattr(seg, "end") else seg["end"])
            if text:
                out.append(TranscriptPiece(start, end, text))
        return out
