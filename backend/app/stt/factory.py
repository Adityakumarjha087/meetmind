"""Select STT / diarization backends from settings."""

from __future__ import annotations

from app.core.config import Settings
from app.stt.base import Diarizer, Transcriber
from app.stt.diarizer import SpectralDiarizer
from app.stt.sidecar import SidecarTranscriber


def build_transcriber(settings: Settings) -> Transcriber:
    if settings.stt_backend == "faster_whisper":  # pragma: no cover - optional heavy dependency
        from app.stt.faster_whisper_backend import FasterWhisperTranscriber

        return FasterWhisperTranscriber(
            settings.whisper_model_size, settings.whisper_device, settings.whisper_compute_type
        )
    if settings.stt_backend == "openai_whisper":
        from openai import OpenAI

        from app.stt.openai_whisper import OpenAIWhisperTranscriber

        if not settings.openai_api_key:
            raise RuntimeError("STT_BACKEND=openai_whisper requires OPENAI_API_KEY")
        return OpenAIWhisperTranscriber(
            OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
        )
    return SidecarTranscriber()


def build_diarizer(settings: Settings) -> Diarizer:
    if settings.diarizer_backend == "pyannote":  # pragma: no cover - optional heavy dependency
        from app.stt.pyannote_backend import PyannoteDiarizer

        return PyannoteDiarizer(settings.hf_token, settings.max_speakers)
    return SpectralDiarizer(settings.diarizer_threshold, settings.max_speakers)
