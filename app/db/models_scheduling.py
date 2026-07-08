"""SQLAlchemy ORM models for the technician-scheduling schema (Alembic rev 0002).

Owned by the technician-scheduling feature (COORDINATION.md §3). Tables:
``technicians``, ``specialties``, ``technician_specialties``, ``service_areas``,
``availability_slots``, ``appointments`` — exact shapes per
``specs/features/2026-07-08-technician-scheduling/requirements.md`` § Contract shapes.

No shared ``DeclarativeBase`` exists yet in the foundation scaffold (the ownership
map assigns no shared ``app/db/base.py``), so this module defines its own. All
primary keys are ``uuid`` to match the ``sessions``/``customers`` uuid-PK
convention used by the voice-diagnostic-core schema (rev 0001), which
``appointments.session_id`` / ``appointments.customer_id`` cross-reference by id
only — no ORM relationship is declared to those tables since ``models_core.py`` is
owned by another feature and isn't importable here.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

APPLIANCE_TYPES: tuple[str, ...] = (
    "washer",
    "dryer",
    "refrigerator",
    "dishwasher",
    "oven",
    "hvac",
)


class Base(DeclarativeBase):
    pass


class Technician(Base):
    """A field technician: identity, contact info, employment details."""

    __tablename__ = "technicians"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    employment_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="full_time"
    )
    hired_on: Mapped[date] = mapped_column(Date, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    __table_args__ = (
        CheckConstraint(
            "employment_type IN ('full_time','contractor')",
            name="ck_technicians_employment_type",
        ),
    )


class Specialty(Base):
    """A lookup row for one of the six appliance types (junction table target)."""

    __tablename__ = "specialties"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)


class TechnicianSpecialty(Base):
    """Junction: which technicians can service which appliance types."""

    __tablename__ = "technician_specialties"

    technician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("technicians.id", ondelete="CASCADE"), primary_key=True
    )
    specialty_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("specialties.id", ondelete="CASCADE"), primary_key=True
    )


class ServiceArea(Base):
    """Junction: which zip codes a technician services."""

    __tablename__ = "service_areas"

    technician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("technicians.id", ondelete="CASCADE"), primary_key=True
    )
    zip_code: Mapped[str] = mapped_column(String(10), primary_key=True)

    __table_args__ = (Index("ix_service_areas_zip_code", "zip_code"),)


class AvailabilitySlot(Base):
    """A pre-generated bookable window on a technician's calendar."""

    __tablename__ = "availability_slots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    technician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("technicians.id", ondelete="CASCADE"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="open")

    __table_args__ = (
        UniqueConstraint("technician_id", "starts_at", name="uq_availability_slots_tech_start"),
        CheckConstraint("status IN ('open','booked')", name="ck_availability_slots_status"),
    )


class Appointment(Base):
    """A confirmed (or cancelled) booking over exactly one claimed slot."""

    __tablename__ = "appointments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("availability_slots.id"), nullable=False, unique=True
    )
    # session_id / customer_id reference tables owned by voice-diagnostic-core's
    # rev 0001 (customers, sessions); left nullable — the standalone
    # `book_appointment` tool signature (contracts.BookAppointment) is not passed a
    # session id, so this column is populated only once the real agent wires a
    # session-scoped caller (integration note, not a schema gap: the FK itself is
    # part of the frozen contract shape).
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True
    )
    technician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("technicians.id"), nullable=False
    )
    appliance_type: Mapped[str] = mapped_column(String(20), nullable=False)
    issue_summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="confirmed")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("status IN ('confirmed','cancelled')", name="ck_appointments_status"),
        CheckConstraint(
            "appliance_type IN ('washer','dryer','refrigerator','dishwasher','oven','hvac')",
            name="ck_appointments_appliance_type",
        ),
    )
