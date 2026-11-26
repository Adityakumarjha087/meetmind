from __future__ import annotations

import json
from datetime import date
from typing import Any

import anthropic
import httpx2
import openai
import pytest

from app.intelligence.llm_engine import INSIGHTS_SCHEMA, LLMEngine
from app.intelligence.summarizer import summarize
from app.intelligence.types import AnalysisInput, ContextChunk, TranscriptLine
from app.llm.anthropic_provider import AnthropicChatModel
from app.llm.base import Completion, LLMError
from app.llm.http_providers import GeminiChatModel, OllamaChatModel
from app.llm.openai_provider import OpenAIChatModel

INSIGHTS = {
    "executive_summary": "The team planned the launch.",
    "key_points": ["Launch is on track"],
    "decisions": [{"text": "Launch on Sept 15", "timestamp_s": 58.7}],
    "action_items": [
        {
            "title": "Fix payment bugs",
            "owner": "Speaker 2",
            "due_date": "2026-12-04",
            "due_text": "next Friday",
            "timestamp_s": 19.6,
        },
        {
            "title": "",
            "owner": None,
            "due_date": "not-a-date",
            "due_text": None,
            "timestamp_s": None,
        },
    ],
    "open_questions": [{"text": "Enough support staff?", "timestamp_s": 44.6}],
    "sentiment": [
        {"speaker": "Speaker 1", "score": 0.6, "label": "positive", "rationale": "upbeat"}
    ],
    "topics": ["launch", "pricing"],
}

LINES = [
    TranscriptLine(0.0, 5.0, "Speaker 1", "Let's plan the launch."),
    TranscriptLine(5.5, 9.0, "Speaker 2", "I will fix the payment bugs by next Friday."),
]


def anthropic_response(text: str, stop: str = "end_turn") -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 120, "output_tokens": 45},
    }


def make_anthropic(handler: Any) -> AnthropicChatModel:
    client = anthropic.Anthropic(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    return AnthropicChatModel(client)


def test_anthropic_structured_output_request_shape() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=anthropic_response(json.dumps(INSIGHTS)))

    model = make_anthropic(handler)
    out = model.complete(system="sys", prompt="hello", json_schema=INSIGHTS_SCHEMA, max_tokens=2000)
    assert out.input_tokens == 120 and out.output_tokens == 45 and out.provider == "anthropic"
    body = seen["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["effort"] == "medium"
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in seen["headers"]["anthropic-beta"]
    assert "thinking" not in body  # Opus 5.5 always thinks adaptively; never send disabled
    assert json.loads(out.text)["topics"] == ["launch", "pricing"]


@pytest.mark.parametrize(
    ("status", "payload", "message"),
    [
        (200, anthropic_response("", "refusal"), "declined"),
        (200, anthropic_response("{", "max_tokens"), "truncated"),
        (
            429,
            {"type": "error", "error": {"type": "rate_limit_error", "message": "slow"}},
            "rate limit",
        ),
        (
            400,
            {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}},
            "API error 400",
        ),
    ],
)
def test_anthropic_error_mapping(status: int, payload: dict[str, Any], message: str) -> None:
    model = make_anthropic(lambda r: httpx2.Response(status, json=payload))
    with pytest.raises(LLMError, match=message):
        model.complete(system="s", prompt="p")


def test_anthropic_connection_error() -> None:
    def boom(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down", request=request)

    with pytest.raises(LLMError, match="reach"):
        make_anthropic(boom).complete(system="s", prompt="p")


def test_openai_provider() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.content)
        return httpx2.Response(
            200,
            json={
                "id": "c1",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": '{"a": 1}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
            },
        )

    client = openai.OpenAI(
        api_key="k",
        max_retries=0,
        http_client=openai.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    out = OpenAIChatModel(client).complete(system="s", prompt="p", json_schema={"type": "object"})
    assert out.text == '{"a": 1}' and out.input_tokens == 11
    assert seen["body"]["response_format"]["json_schema"]["strict"] is True
    failing = openai.OpenAI(
        api_key="k",
        max_retries=0,
        http_client=openai.DefaultHttpxClient(
            transport=httpx2.MockTransport(lambda r: httpx2.Response(500, json={}))
        ),
    )
    with pytest.raises(LLMError):
        OpenAIChatModel(failing).complete(system="s", prompt="p")


def test_gemini_and_ollama_providers() -> None:
    def gemini(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["x-goog-api-key"] == "g"
        body = json.loads(request.content)
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        return httpx2.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "{}"}]}}],
                "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 2},
            },
        )

    g = GeminiChatModel("g", client=httpx2.Client(transport=httpx2.MockTransport(gemini)))
    assert g.complete(system="s", prompt="p", json_schema={"type": "object"}).input_tokens == 7
    bad = GeminiChatModel(
        "g",
        client=httpx2.Client(
            transport=httpx2.MockTransport(lambda r: httpx2.Response(200, json={"candidates": []}))
        ),
    )
    with pytest.raises(LLMError):
        bad.complete(system="s", prompt="p")

    def ollama(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        assert body["format"] == {"type": "object"} and body["stream"] is False
        return httpx2.Response(
            200, json={"message": {"content": "{}"}, "prompt_eval_count": 5, "eval_count": 1}
        )

    o = OllamaChatModel(client=httpx2.Client(transport=httpx2.MockTransport(ollama)))
    assert o.complete(system="s", prompt="p", json_schema={"type": "object"}).output_tokens == 1
    down = OllamaChatModel(
        client=httpx2.Client(transport=httpx2.MockTransport(lambda r: httpx2.Response(503)))
    )
    with pytest.raises(LLMError):
        down.complete(system="s", prompt="p")


class ScriptedModel:
    provider = "fake"
    model = "scripted"

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.prompts: list[str] = []

    def complete(
        self,
        *,
        system: str,
        prompt: str,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int = 16000,
    ) -> Completion:
        self.prompts.append(prompt)
        return Completion(self.replies.pop(0), 100, 20, self.provider, self.model)


def test_llm_engine_validates_and_repairs() -> None:
    model = ScriptedModel(["not json", "```json\n" + json.dumps(INSIGHTS) + "\n```"])
    engine = LLMEngine(model)
    result = engine.analyze(AnalysisInput("Launch", date(2026, 11, 26), LINES))
    ins = result.insights
    assert len(model.prompts) == 2 and "invalid" in model.prompts[1]
    assert [a.title for a in ins.action_items] == ["Fix payment bugs"]  # malformed item dropped
    assert ins.action_items[0].due_date == date(2026, 12, 4)
    assert {s.speaker for s in ins.sentiment} == {
        "Speaker 1",
        "Speaker 2",
    }  # talk time attached for all
    assert ins.engine == "fake:scripted" and len(result.usage) == 2


def test_llm_engine_gives_up_after_two_invalid_replies() -> None:
    with pytest.raises(LLMError):
        LLMEngine(ScriptedModel(["nope", "[1, 2]"])).analyze(
            AnalysisInput("x", date(2026, 1, 1), LINES)
        )


def test_llm_map_reduce_and_answer() -> None:
    long_lines = [
        TranscriptLine(i * 300.0, i * 300.0 + 10, f"Speaker {i % 2 + 1}", f"Point number {i}.")
        for i in range(30)
    ]
    replies = [json.dumps(INSIGHTS)] * 4
    model = ScriptedModel(replies)
    result = summarize(
        LLMEngine(model),
        AnalysisInput("Long", date(2026, 1, 1), long_lines),
        long_threshold_s=3600,
        chunk_s=3000,
    )
    assert result.insights.strategy == "map_reduce" and result.insights.chunks_processed == 3
    assert "## Section 3" in model.prompts[-1]
    assert len(result.usage) == 4

    answer_model = ScriptedModel(
        [json.dumps({"answer": "Launch is Sept 15 [1].", "citations": [1, 99]})]
    )
    ctx = [
        ContextChunk(1, "m1", "Launch", 0.0, 10.0, ["Speaker 1"], "We agreed to launch on Sept 15.")
    ]
    ans = LLMEngine(answer_model).answer("When is launch?", ctx)
    assert ans.cited == [1] and "Sept 15" in ans.answer
    assert LLMEngine(ScriptedModel([])).answer("q", []).cited == []
