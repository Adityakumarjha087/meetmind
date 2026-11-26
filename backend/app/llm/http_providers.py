"""REST-based providers: Google Gemini and local Ollama (via httpx2)."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx2

from app.llm.base import Completion, LLMError


class GeminiChatModel:
    provider = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        client: httpx2.Client | None = None,
        base_url: str = "https://generativelanguage.googleapis.com",
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._client = client or httpx2.Client(timeout=120.0)
        self._base = base_url.rstrip("/")

    def complete(
        self,
        *,
        system: str,
        prompt: str,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int = 16000,
    ) -> Completion:
        gen: dict[str, Any] = {"maxOutputTokens": max_tokens}
        user_text = prompt
        if json_schema is not None:
            gen["responseMimeType"] = "application/json"
            user_text += "\n\nReturn JSON matching this JSON Schema:\n" + json.dumps(json_schema)
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user_text}]}],
            "generationConfig": gen,
        }
        started = time.perf_counter()
        try:
            resp = self._client.post(
                f"{self._base}/v1beta/models/{self.model}:generateContent",
                headers={"x-goog-api-key": self._api_key},
                json=body,
            )
            resp.raise_for_status()
        except httpx2.HTTPError as exc:
            raise LLMError(f"Gemini request failed: {exc}") from exc
        data = resp.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError) as exc:
            raise LLMError("Gemini returned no candidates") from exc
        usage = data.get("usageMetadata", {})
        return Completion(
            text="".join(p.get("text", "") for p in parts),
            input_tokens=int(usage.get("promptTokenCount", 0)),
            output_tokens=int(usage.get("candidatesTokenCount", 0)),
            provider=self.provider,
            model=self.model,
            latency_ms=(time.perf_counter() - started) * 1000,
        )


class OllamaChatModel:
    provider = "ollama"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.1",
        client: httpx2.Client | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self.model = model
        self._client = client or httpx2.Client(timeout=600.0)

    def complete(
        self,
        *,
        system: str,
        prompt: str,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int = 16000,
    ) -> Completion:
        body: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "options": {"num_predict": max_tokens, "temperature": 0.1},
        }
        if json_schema is not None:
            body["format"] = json_schema
        started = time.perf_counter()
        try:
            resp = self._client.post(f"{self._base}/api/chat", json=body)
            resp.raise_for_status()
        except httpx2.HTTPError as exc:
            raise LLMError(f"Ollama request failed: {exc}") from exc
        data = resp.json()
        return Completion(
            text=data.get("message", {}).get("content", ""),
            input_tokens=int(data.get("prompt_eval_count", 0)),
            output_tokens=int(data.get("eval_count", 0)),
            provider=self.provider,
            model=self.model,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
