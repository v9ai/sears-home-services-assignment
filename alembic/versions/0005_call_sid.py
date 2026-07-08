"""sessions: call_sid column

Revision ID: 0005_call_sid
Revises: 0004_merge
Create Date: 2026-07-08

Adds ``sessions.call_sid`` (nullable, phone channel only) so a session can be
correlated back to its Twilio ``CallSid`` -- needed to look up native Twilio call
recordings for that call via the REST API.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_call_sid"
down_revision: str | None = "0004_merge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("call_sid", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "call_sid")
