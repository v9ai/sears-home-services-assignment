"""Core ORM models — Alembic rev ``0001_core`` (COORDINATION.md §2).

Table shapes mirror ``requirements.md`` § Contract shapes verbatim:
- ``customers(id, name, phone, email, created_at)``
- ``sessions(id uuid PK, customer_id FK null, channel text CHECK IN ('web','phone')
  DEFAULT 'web', appliance_type text null, case_file jsonb DEFAULT '{}',
  transcript jsonb DEFAULT '[]', started_at, ended_at)``
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    sessions: Mapped[list[SessionRecord]] = relationship(back_populates="customer")


class SessionRecord(Base):
    __tablename__ = "sessions"
    __table_args__ = (CheckConstraint("channel IN ('web', 'phone')", name="ck_sessions_channel"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True
    )
    channel: Mapped[str] = mapped_column(String, nullable=False, server_default="web")
    appliance_type: Mapped[str | None] = mapped_column(String, nullable=True)
    case_file: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    transcript: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    customer: Mapped[Customer | None] = relationship(back_populates="sessions")
