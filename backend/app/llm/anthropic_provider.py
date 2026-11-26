"""Claude via the official Anthropic SDK, with structured outputs and server-side refusal fallback."""

from __future__ import annotations

import time
from typing import Any

import anthropic
from anthropic.types.beta import BetaMessageParam, BetaOutputConfigParam

from app.llm.base import Completion, LLMError


class AnthropicChatModel:
    provider = "anthropic"

    def __init__(
        self, client: anthropic.Anthropic, model: str = "claude-opus-5-5", effort: str = "medium"
    ) -> None:
        self._client = client
        self.model = model
        self.effort = effort

    def complete(
        self,
        *,
        system: str,
        prompt: str,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int = 16000,
    ) -> Completion:
        output_config: BetaOutputConfigParam = {"effort": self.effort}  # type: ignore[typeddict-item]
        if json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": json_schema}
        messages: list[BetaMessageParam] = [{"role": "user", "content": prompt}]
        started = time.perf_counter()
        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                output_config=output_config,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError as exc:
            raise LLMError("Anthropic rate limit exceeded") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Could not reach the Anthropic API") from exc
        if response.stop_reason == "refusal":
            raise LLMError("The model declined to process this transcript")
        if response.stop_reason == "max_tokens":
            raise LLMError("The model response was truncated (max_tokens)")
        text = "".join(block.text for block in response.content if block.type == "text")
        return Completion(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            provider=self.provider,
            model=response.model or self.model,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
