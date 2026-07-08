"""Technician scheduling schema (Tier 2)

Revision ID: 0002_scheduling
Revises: 0001_core
Create Date: 2026-07-08

Creates the six scheduling tables per
``specs/features/2026-07-08-technician-scheduling/requirements.md`` § Contract
shapes: technicians, specialties, technician_specialties, service_areas,
availability_slots, appointments.

Pre-allocated revision id per COORDINATION.md §2. ``down_revision`` points at
``0001_core`` (owned by voice-diagnostic-core); during parallel development that
revision file does not exist in every agent's isolated worktree — multiple
Alembic heads are expected (COORDINATION.md §2), and the lead adds a merge
revision at integration. ``appointments.session_id`` / ``customer_id`` reference
``sessions`` / ``customers`` (created by 0001_core), which is exactly why this
revision cannot be its own root.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_scheduling"
down_revision: str | None = "0001_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "technicians",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("employment_type", sa.String(20), nullable=False, server_default="full_time"),
        sa.Column("hired_on", sa.Date(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint(
            "employment_type IN ('full_time','contractor')",
            name="ck_technicians_employment_type",
        ),
        sa.UniqueConstraint("email", name="uq_technicians_email"),
    )

    op.create_table(
        "specialties",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(30), nullable=False),
        sa.UniqueConstraint("name", name="uq_specialties_name"),
    )

    op.create_table(
        "technician_specialties",
        sa.Column(
            "technician_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("technicians.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "specialty_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("specialties.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "service_areas",
        sa.Column(
            "technician_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("technicians.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("zip_code", sa.String(10), primary_key=True),
    )
    op.create_index("ix_service_areas_zip_code", "service_areas", ["zip_code"])

    op.create_table(
        "availability_slots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "technician_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("technicians.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="open"),
        sa.CheckConstraint("status IN ('open','booked')", name="ck_availability_slots_status"),
        sa.UniqueConstraint("technician_id", "starts_at", name="uq_availability_slots_tech_start"),
    )

    op.create_table(
        "appointments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "slot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("availability_slots.id"),
            nullable=False,
        ),
        sa.Column(
            "session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=True
        ),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id"),
            nullable=True,
        ),
        sa.Column(
            "technician_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("technicians.id"),
            nullable=False,
        ),
        sa.Column("appliance_type", sa.String(20), nullable=False),
        sa.Column("issue_summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="confirmed"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("status IN ('confirmed','cancelled')", name="ck_appointments_status"),
        sa.CheckConstraint(
            "appliance_type IN ('washer','dryer','refrigerator','dishwasher','oven','hvac')",
            name="ck_appointments_appliance_type",
        ),
        sa.UniqueConstraint("slot_id", name="uq_appointments_slot_id"),
    )


def downgrade() -> None:
    op.drop_table("appointments")
    op.drop_table("availability_slots")
    op.drop_index("ix_service_areas_zip_code", table_name="service_areas")
    op.drop_table("service_areas")
    op.drop_table("technician_specialties")
    op.drop_table("specialties")
    op.drop_table("technicians")
