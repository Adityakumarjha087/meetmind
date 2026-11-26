from __future__ import annotations

from typing import Any


class OpenAIEmbedder:
    name = "openai"

    def __init__(self, client: Any, model: str = "text-embedding-3-small", dim: int = 384) -> None:
        self._client = client
        self.model = model
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for i in range(0, len(texts), 256):
            resp = self._client.embeddings.create(
                model=self.model, input=texts[i : i + 256], dimensions=self.dim
            )
            out.extend([list(map(float, d.embedding)) for d in resp.data])
        return out
