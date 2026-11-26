"""Cost model for transcription and LLM usage."""

from __future__ import annotations

from app.core.config import Settings


def stt_cost(settings: Settings, backend: str, audio_seconds: float) -> float:
    per_min = settings.cost_stt_per_minute.get(backend, 0.0)
    return round(per_min * audio_seconds / 60.0, 6)


def stt_projected_cost(settings: Settings, audio_seconds: float) -> float:
    return round(settings.reference_stt_per_minute * audio_seconds / 60.0, 6)


def llm_cost(
    settings: Settings, provider: str, model: str, input_tokens: int, output_tokens: int
) -> float:
    if provider in {"offline", "ollama"}:
        return 0.0
    inp, out = settings.llm_prices_per_mtok.get(model, (0.0, 0.0))
    return round((input_tokens * inp + output_tokens * out) / 1_000_000, 6)


def llm_projected_cost(settings: Settings, input_tokens: int, output_tokens: int) -> float:
    return round(
        (
            input_tokens * settings.reference_llm_input_per_mtok
            + output_tokens * settings.reference_llm_output_per_mtok
        )
        / 1_000_000,
        6,
    )
