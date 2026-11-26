"""faster-whisper (CTranslate2 Whisper) transcriber. Optional: `uv sync --extra ml`."""

from __future__ import annotations

from typing import Any

from app.stt.base import TranscriptionContext, TranscriptPiece


class FasterWhisperTranscriber:
    name = "faster_whisper"

    def __init__(self, model_size: str = "base", device: str = "auto", compute_type: str = "int8") -> None:
        from faster_whisper import WhisperModel

        self._model: Any = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, ctx: TranscriptionContext) -> list[TranscriptPiece]:
        segments, _info = self._model.transcribe(
            str(ctx.audio_path), language=ctx.language, vad_filter=True, beam_size=5
        )
        out: list[TranscriptPiece] = []
        for seg in segments:
            text = seg.text.strip()
            if text:
                conf = float(min(1.0, max(0.0, 1.0 + seg.avg_logprob)))
                out.append(TranscriptPiece(float(seg.start), float(seg.end), text, conf))
        return out
