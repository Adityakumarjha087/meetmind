"""Semantic search over transcript chunks (pgvector cosine on Postgres, NumPy elsewhere) + RAG answers."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.embeddings.base import Embedder
from app.intelligence.types import AnswerResult, ContextChunk, InsightEngine
from app.models import Meeting, TranscriptChunk


@dataclass(frozen=True)
class SearchHit:
    chunk: TranscriptChunk
    meeting: Meeting
    score: float


def semantic_search(
    db: Session,
    embedder: Embedder,
    workspace_id: str,
    query: str,
    top_k: int = 6,
    meeting_id: str | None = None,
) -> list[SearchHit]:
    qvec = embedder.embed([query])[0]
    base = (
        select(TranscriptChunk, Meeting)
        .join(Meeting, Meeting.id == TranscriptChunk.meeting_id)
        .where(TranscriptChunk.workspace_id == workspace_id)
    )
    if meeting_id:
        base = base.where(TranscriptChunk.meeting_id == meeting_id)
    if db.get_bind().dialect.name == "postgresql":
        distance = TranscriptChunk.embedding.cosine_distance(qvec)
        rows = db.execute(
            base.add_columns(distance.label("d")).order_by(distance).limit(top_k)
        ).all()
        hits = [SearchHit(r[0], r[1], round(1.0 - float(r[2]), 4)) for r in rows]
    else:
        rows = db.execute(base).all()
        if not rows:
            return []
        mat = np.array([r[0].embedding for r in rows], dtype=np.float64)
        q = np.array(qvec, dtype=np.float64)
        norms = np.linalg.norm(mat, axis=1) * (np.linalg.norm(q) or 1.0)
        sims = (mat @ q) / np.where(norms == 0, 1.0, norms)
        order = np.argsort(-sims)[:top_k]
        hits = [SearchHit(rows[i][0], rows[i][1], round(float(sims[i]), 4)) for i in order]
    return [h for h in hits if h.score > 0.0]


def answer_question(
    db: Session,
    engine: InsightEngine,
    embedder: Embedder,
    workspace_id: str,
    question: str,
    meeting_id: str | None = None,
) -> tuple[AnswerResult, list[ContextChunk]]:
    hits = semantic_search(
        db, embedder, workspace_id, question, get_settings().rag_top_k, meeting_id
    )
    contexts = [
        ContextChunk(
            index=i + 1,
            meeting_id=h.meeting.id,
            meeting_title=h.meeting.title,
            start_s=h.chunk.start_s,
            end_s=h.chunk.end_s,
            speakers=list(h.chunk.speakers or []),
            text=h.chunk.text,
            score=h.score,
        )
        for i, h in enumerate(hits)
    ]
    return engine.answer(question, contexts), contexts
