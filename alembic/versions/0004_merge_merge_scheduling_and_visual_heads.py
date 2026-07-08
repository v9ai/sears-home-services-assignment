"""merge scheduling and visual heads

Revision ID: 0004_merge
Revises: 0002_scheduling, 0003_visual
Create Date: 2026-07-08 19:58:57.501458

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004_merge'
down_revision: str | None = ('0002_scheduling', '0003_visual')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
