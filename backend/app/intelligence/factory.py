"""Build the configured insight engine (offline heuristics or an LLM provider)."""

from __future__ import annotations

from app.core.config import Settings
from app.intelligence.heuristic import HeuristicEngine
from app.intelligence.llm_engine import LLMEngine
from app.intelligence.types import InsightEngine
from app.llm.base import ChatModel


def build_chat_model(settings: Settings) -> ChatModel | None:
    provider = settings.llm_provider
    if provider == "anthropic":
        import anthropic

        from app.llm.anthropic_provider import AnthropicChatModel

        if not settings.anthropic_api_key:
            raise RuntimeError("LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
        return AnthropicChatModel(
            anthropic.Anthropic(api_key=settings.anthropic_api_key),
            settings.llm_model or settings.anthropic_model,
        )
    if provider == "openai":
        import openai

        from app.llm.openai_provider import OpenAIChatModel

        if not settings.openai_api_key:
            raise RuntimeError("LLM_PROVIDER=openai requires OPENAI_API_KEY")
        return OpenAIChatModel(
            openai.OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url),
            settings.llm_model or settings.openai_model,
        )
    if provider == "gemini":
        from app.llm.http_providers import GeminiChatModel

        if not settings.gemini_api_key:
            raise RuntimeError("LLM_PROVIDER=gemini requires GEMINI_API_KEY")
        return GeminiChatModel(settings.gemini_api_key, settings.llm_model or settings.gemini_model)
    if provider == "ollama":
        from app.llm.http_providers import OllamaChatModel

        return OllamaChatModel(
            settings.ollama_base_url, settings.llm_model or settings.ollama_model
        )
    return None


def build_engine(settings: Settings) -> InsightEngine:
    model = build_chat_model(settings)
    if model is None:
        return HeuristicEngine()
    return LLMEngine(model, settings.llm_max_tokens)
