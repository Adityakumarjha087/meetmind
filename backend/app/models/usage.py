from __future__ import annotations

from sqlalchemy import Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin
from app.models.enums import UsageKind


class UsageEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "usage_events"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    meeting_id: Mapped[str | None] = mapped_column(
        ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[UsageKind] = mapped_column(
        Enum(UsageKind, name="usage_kind", values_callable=lambda e: [m.value for m in e])
    )
    provider: Mapped[str] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    audio_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    projected_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
