from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.embeddings.factory import build_embedder
from app.intelligence.factory import build_engine
from app.models import Role
from app.schemas.api import AskIn, AskOut, CitationOut, SearchHitOut
from app.services.access import require_role
from app.services.pipeline import record_llm_usage
from app.services.search import answer_question, semantic_search

router = APIRouter(tags=["ask"])


@router.post("/workspaces/{workspace_id}/ask", response_model=AskOut)
def ask(workspace_id: str, body: AskIn, user: CurrentUser, db: DB) -> AskOut:
    """RAG over every meeting in the workspace, with timestamped citations."""
    require_role(db, user, workspace_id, Role.VIEWER)
    settings = get_settings()
    engine = build_engine(settings)
    result, contexts = answer_question(
        db, engine, build_embedder(settings), workspace_id, body.question, body.meeting_id
    )
    record_llm_usage(db, settings, workspace_id, None, result.usage)
    db.commit()
    by_index = {c.index: c for c in contexts}
    citations = [
        CitationOut(
            index=i,
            meeting_id=by_index[i].meeting_id,
            meeting_title=by_index[i].meeting_title,
            start_s=by_index[i].start_s,
            end_s=by_index[i].end_s,
            speakers=by_index[i].speakers,
            text=by_index[i].text,
            score=by_index[i].score,
        )
        for i in result.cited
        if i in by_index
    ]
    return AskOut(answer=result.answer, citations=citations, engine=engine.name)


@router.get("/workspaces/{workspace_id}/search", response_model=list[SearchHitOut])
def search(
    workspace_id: str,
    user: CurrentUser,
    db: DB,
    q: Annotated[str, Query(min_length=2, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[SearchHitOut]:
    require_role(db, user, workspace_id, Role.VIEWER)
    hits = semantic_search(db, build_embedder(get_settings()), workspace_id, q, limit)
    return [
        SearchHitOut(
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
