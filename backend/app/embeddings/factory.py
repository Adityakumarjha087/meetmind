from __future__ import annotations

from app.core.config import Settings
from app.embeddings.base import Embedder
from app.embeddings.hashing import HashingEmbedder


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedding_backend == "openai":
        import openai

        from app.embeddings.openai_embedder import OpenAIEmbedder

        if not settings.openai_api_key:
            raise RuntimeError("EMBEDDING_BACKEND=openai requires OPENAI_API_KEY")
        return OpenAIEmbedder(
            openai.OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url),
            settings.openai_embedding_model,
            settings.embedding_dim,
        )
    return HashingEmbedder(settings.embedding_dim)
