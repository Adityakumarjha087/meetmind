"""Usage dashboard aggregation."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Meeting, MeetingStatus, UsageEvent, UsageKind


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def workspace_usage(db: Session, workspace_id: str, days: int = 30) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    events = list(
        db.scalars(
            select(UsageEvent).where(UsageEvent.workspace_id == workspace_id, UsageEvent.created_at >= since)
        )
    )
    meetings = list(
        db.scalars(
            select(Meeting).where(
                Meeting.workspace_id == workspace_id,
                Meeting.status == MeetingStatus.COMPLETED,
                Meeting.processing_finished_at.is_not(None),
                Meeting.processing_finished_at >= since,
            )
        )
    )
    stt = [e for e in events if e.kind == UsageKind.STT]
    llm = [e for e in events if e.kind == UsageKind.LLM]
    minutes = sum(e.audio_seconds for e in stt) / 60.0

    proc_times: list[float] = []
    rtf: list[float] = []
    stage_totals: dict[str, float] = defaultdict(float)
    for m in meetings:
        if m.processing_started_at and m.processing_finished_at:
            secs = (_aware(m.processing_finished_at) - _aware(m.processing_started_at)).total_seconds()
            proc_times.append(secs)
            if m.duration_s:
                rtf.append(secs / m.duration_s)
        for stage, t in (m.stage_timings or {}).items():
            stage_totals[stage] += float(t)

    daily: dict[str, dict[str, float]] = {}
    for i in range(days):
        d = (datetime.now(UTC) - timedelta(days=days - 1 - i)).date().isoformat()
        daily[d] = {"minutes": 0.0, "cost_usd": 0.0, "projected_cost_usd": 0.0, "meetings": 0}
    for e in events:
        d = _aware(e.created_at).date().isoformat()
        if d in daily:
            daily[d]["minutes"] += e.audio_seconds / 60.0 if e.kind == UsageKind.STT else 0.0
            daily[d]["cost_usd"] += e.cost_usd
            daily[d]["projected_cost_usd"] += e.projected_cost_usd
            daily[d]["meetings"] += 1 if e.kind == UsageKind.STT else 0

    by_provider: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {"events": 0, "input_tokens": 0, "output_tokens": 0, "audio_minutes": 0.0, "cost_usd": 0.0}
    )
    for e in events:
        row = by_provider[(e.kind.value, e.provider)]
        row["events"] += 1
        row["input_tokens"] += e.input_tokens
        row["output_tokens"] += e.output_tokens
        row["audio_minutes"] += e.audio_seconds / 60.0
        row["cost_usd"] += e.cost_usd

    n = len(proc_times)
    return {
        "days": days,
        "totals": {
            "meetings_processed": len(meetings),
            "minutes_transcribed": round(minutes, 2),
            "avg_processing_seconds": round(sum(proc_times) / n, 3) if n else 0.0,
            "avg_realtime_factor": round(sum(rtf) / len(rtf), 4) if rtf else 0.0,
            "llm_input_tokens": sum(e.input_tokens for e in llm),
            "llm_output_tokens": sum(e.output_tokens for e in llm),
            "cost_usd": round(sum(e.cost_usd for e in events), 4),
            "projected_hosted_cost_usd": round(sum(e.projected_cost_usd for e in events), 4),
            "cost_per_meeting_usd": round(sum(e.cost_usd for e in events) / len(meetings), 4) if meetings else 0.0,
        },
        "daily": [{"date": d, **{k: round(v, 4) for k, v in vals.items()}} for d, vals in daily.items()],
        "by_provider": [
            {"kind": k, "provider": p, **{key: round(v, 4) for key, v in vals.items()}}
            for (k, p), vals in sorted(by_provider.items())
        ],
        "stage_seconds": {k: round(v, 3) for k, v in sorted(stage_totals.items())},
    }
