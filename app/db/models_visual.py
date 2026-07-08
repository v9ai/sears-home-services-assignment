"""SQLAlchemy Core tables for the visual-diagnosis feature (rev ``0003_visual``).

Owned by visual-diagnosis (COORDINATION.md §3). Uses Core ``Table`` objects (not a
shared declarative ``Base`` — none exists yet in the foundation scaffold) so this
module has no import-time dependency on ``app.db.models_core`` (owned by
voice-diagnostic-core, developed in parallel and possibly absent from this worktree).

``sessions_ref`` declares only the columns visual-diagnosis reads/writes
(``id``, ``case_file``, ``ended_at``) on the ``sessions`` table that
``0001_core`` creates. It is a read/write reference for cross-feature case-file
merges, not ownership of the sessions schema.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

metadata = sa.MetaData()

image_uploads = sa.Table(
    "image_uploads",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("email", sa.Text(), nullable=False),
    sa.Column("token", sa.String(length=64), nullable=False, unique=True),
    sa.Column("image_path", sa.Text(), nullable=True),
    sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
    sa.Column("vision_analysis", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
)

# Cross-feature reference: subset of the ``sessions`` table (owned by
# voice-diagnostic-core, rev 0001_core) needed to merge vision findings into the
# session's case file and to tell whether the call has already ended.
sessions_ref = sa.Table(
    "sessions",
    sa.MetaData(),
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column("case_file", postgresql.JSONB(astext_type=sa.Text())),
    sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
)
