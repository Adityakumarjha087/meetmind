"""Offline feature-hashing embedder (unigrams + bigrams, signed hashing, sublinear TF, L2-normalised).

Not semantic in the neural sense, but deterministic, fast and dependency-free - a reasonable
lexical-retrieval fallback that keeps pgvector search working without any model or API key.
"""

from __future__ import annotations

import hashlib
import itertools
import math

from app.intelligence.text import content_terms


class HashingEmbedder:
    name = "hashing"

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def _features(self, text: str) -> dict[str, float]:
        terms = content_terms(text)
        feats: dict[str, float] = {}
        for t in terms:
            feats[t] = feats.get(t, 0.0) + 1.0
        for a, b in itertools.pairwise(terms):
            key = f"{a}_{b}"
            feats[key] = feats.get(key, 0.0) + 0.5
        return feats

    def embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for feat, count in self._features(text).items():
            digest = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[idx] += sign * (1.0 + math.log(count)) if count >= 1 else sign * count
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm > 0 else vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]
