"""visual diagnosis: image_uploads table

Revision ID: 0003_visual
Revises: 0001_core
Create Date: 2026-07-08

Owned by the visual-diagnosis feature triplet (COORDINATION.md §3). Revision id and
down_revision are pre-allocated in COORDINATION.md §2: ``0003_visual`` branches off
``0001_core`` (not ``0002_scheduling``), so scheduling and visual can both land on top
of the core schema independently. During parallel development ``0001_core`` may not
exist yet in this worktree (multiple Alembic heads expected); the lead adds a merge
revision at integration (COORDINATION.md §5).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_visual"
down_revision: str | None = "0001_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "image_uploads",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False, unique=True),
        sa.Column("image_path", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("vision_analysis", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'uploaded', 'analyzed', 'expired')",
            name="ck_image_uploads_status",
        ),
    )
    op.create_index("ix_image_uploads_token", "image_uploads", ["token"], unique=True)
    op.create_index("ix_image_uploads_session_id", "image_uploads", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_image_uploads_session_id", table_name="image_uploads")
    op.drop_index("ix_image_uploads_token", table_name="image_uploads")
    op.drop_table("image_uploads")
