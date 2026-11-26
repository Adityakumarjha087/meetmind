"""Tokenisation helpers shared by the offline engine and the hashing embedder."""

from __future__ import annotations

import re

STOPWORDS = frozenset(
    [
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "has",
        "have",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "itself",
        "just",
        "let",
        "lets",
        "let's",
        "me",
        "more",
        "most",
        "my",
        "myself",
        "no",
        "nor",
        "not",
        "now",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "our",
        "ours",
        "ourselves",
        "out",
        "over",
        "own",
        "same",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "that's",
        "the",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "we",
        "we'll",
        "we're",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "i'm",
        "i'll",
        "i've",
        "you're",
        "it's",
        "yes",
        "yeah",
        "okay",
        "ok",
        "um",
        "uh",
        "like",
        "really",
        "also",
        "get",
        "got",
        "going",
        "go",
        "one",
        "two",
        "well",
        "think",
        "thanks",
        "thank",
        "everyone",
        "good",
        "great",
        "right",
        "sure",
        "know",
        "want",
        "need",
        "still",
        "yet",
        "much",
        "many",
        "lot",
        "next",
        "last",
        "today",
    ]
)

_WORD = re.compile(r"[a-z0-9][a-z0-9'\-]*")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def stem(token: str) -> str:
    """Tiny suffix-stripper: enough to conflate decide/decided/decision-style variants."""
    for suffix in ("ingly", "ing", "edly", "ed", "ies", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            token = token[: -len(suffix)] + ("y" if suffix == "ies" else "")
            break
    if len(token) > 4 and token.endswith("e"):
        token = token[:-1]
    return token


def content_terms(text: str) -> list[str]:
    return [stem(w.strip("'-")) for w in words(text) if w not in STOPWORDS and len(w) > 2]


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text.strip()) if s.strip()]


def normalize_for_dedupe(text: str) -> frozenset[str]:
    return frozenset(content_terms(text))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / max(1, len(a | b))
