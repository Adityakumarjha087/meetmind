"""Provider-agnostic chat-model interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    provider: str
    model: str
    latency_ms: float = 0.0


class ChatModel(Protocol):
    provider: str
    model: str

    def complete(
        self,
        *,
        system: str,
        prompt: str,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int = 16000,
    ) -> Completion: ...


def estimate_tokens(text: str) -> int:
    """~4 characters per token heuristic, used for offline cost projections."""
    return max(1, len(text) // 4)
