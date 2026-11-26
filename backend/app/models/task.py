from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin
from app.models.enums import ActionStatus
from app.models.meeting import Meeting
from app.models.user import User


class ActionItem(IdMixin, TimestampMixin, Base):
    __tablename__ = "action_items"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    meeting_id: Mapped[str | None] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    assignee_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[ActionStatus] = mapped_column(
        Enum(ActionStatus, name="action_status", values_callable=lambda e: [m.value for m in e]),
        default=ActionStatus.TODO,
        index=True,
    )
    position: Mapped[float] = mapped_column(Float, default=0.0)
    source_start_s: Mapped[float | None] = mapped_column(Float, nullable=True)

    meeting: Mapped[Meeting | None] = relationship()
    assignee: Mapped[User | None] = relationship()
