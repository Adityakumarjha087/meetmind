"""OpenAI chat completions with strict JSON-schema structured outputs."""

from __future__ import annotations

import time
from typing import Any

import openai

from app.llm.base import Completion, LLMError


class OpenAIChatModel:
    provider = "openai"

    def __init__(self, client: openai.OpenAI, model: str = "gpt-4o-mini") -> None:
        self._client = client
        self.model = model

    def complete(
        self,
        *,
        system: str,
        prompt: str,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int = 16000,
    ) -> Completion:
        kwargs: dict[str, Any] = {}
        if json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "meetmind_output", "schema": json_schema, "strict": True},
            }
        started = time.perf_counter()
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                max_completion_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                **kwargs,
            )
        except openai.APIStatusError as exc:
            raise LLMError(f"OpenAI API error {exc.status_code}") from exc
        except openai.APIConnectionError as exc:
            raise LLMError("Could not reach the OpenAI API") from exc
        choice = response.choices[0]
        if getattr(choice.message, "refusal", None):
            raise LLMError("The model declined to process this transcript")
        usage = response.usage
        return Completion(
            text=choice.message.content or "",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            provider=self.provider,
            model=response.model or self.model,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
