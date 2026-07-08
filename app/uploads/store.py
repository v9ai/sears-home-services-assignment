"""Upload token/record storage.

``UploadStore`` is a small Protocol so the token-lifecycle logic (expiry, single-use,
status transitions) is testable without a live Postgres (COORDINATION.md §4 stub seam:
"mock the OpenAI vision call in tests" / "fake a session row"). ``InMemoryUploadStore``
backs the test suite and offline/dev runs; ``PostgresUploadStore`` is the real runtime
implementation against ``image_uploads`` (rev ``0003_visual``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import sqlalchemy as sa
from pydantic import BaseModel, Field

from app.db.models_visual import image_uploads
from app.uploads import tokens
from app.uploads.db import connect

UploadStatus = Literal["pending", "uploaded", "analyzed", "expired"]


class UploadRecord(BaseModel):
    """Mirrors an ``image_uploads`` row."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    session_id: uuid.UUID
    email: str
    token: str
    image_path: str | None = None
    status: UploadStatus = "pending"
    vision_analysis: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime


class UploadStore(Protocol):
    """Token/record lifecycle, independent of the storage backend."""

    async def create(self, session_id: uuid.UUID, email: str) -> UploadRecord: ...

    async def get_by_token(self, token: str) -> UploadRecord | None: ...

    async def latest_for_session(self, session_id: uuid.UUID) -> UploadRecord | None: ...

    async def save_image(self, token: str, image_path: str) -> UploadRecord: ...

    async def save_analysis(self, token: str, analysis: dict[str, Any]) -> UploadRecord: ...


def _effective_status(record: UploadRecord, now: datetime | None = None) -> UploadStatus:
    """Expiry is time-derived, not just a stored flag: a 'pending'/'uploaded' token past
    its TTL reads as 'expired' even if nothing has written that status yet."""
    if record.status in ("pending", "uploaded") and tokens.is_expired(record.expires_at, now):
        return "expired"
    return record.status


class InMemoryUploadStore:
    """Test/offline-dev backend — no Postgres required."""

    def __init__(self) -> None:
        self._by_token: dict[str, UploadRecord] = {}

    async def create(self, session_id: uuid.UUID, email: str) -> UploadRecord:
        record = UploadRecord(
            session_id=session_id,
            email=email,
            token=tokens.generate_token(),
            expires_at=tokens.new_expiry(),
        )
        self._by_token[record.token] = record
        return record

    async def get_by_token(self, token: str) -> UploadRecord | None:
        record = self._by_token.get(token)
        if record is None:
            return None
        effective = _effective_status(record)
        if effective != record.status:
            record = record.model_copy(update={"status": effective})
            self._by_token[token] = record
        return record

    async def latest_for_session(self, session_id: uuid.UUID) -> UploadRecord | None:
        candidates = [r for r in self._by_token.values() if r.session_id == session_id]
        if not candidates:
            return None
        latest = max(candidates, key=lambda r: r.created_at)
        return await self.get_by_token(latest.token)

    async def save_image(self, token: str, image_path: str) -> UploadRecord:
        record = self._by_token[token]
        updated = record.model_copy(update={"image_path": image_path, "status": "uploaded"})
        self._by_token[token] = updated
        return updated

    async def save_analysis(self, token: str, analysis: dict[str, Any]) -> UploadRecord:
        record = self._by_token[token]
        updated = record.model_copy(update={"vision_analysis": analysis, "status": "analyzed"})
        self._by_token[token] = updated
        return updated


class PostgresUploadStore:
    """Real runtime backend against the ``image_uploads`` table."""

    @staticmethod
    def _row_to_record(row: Any) -> UploadRecord:
        return UploadRecord(
            id=row.id,
            session_id=row.session_id,
            email=row.email,
            token=row.token,
            image_path=row.image_path,
            status=row.status,
            vision_analysis=row.vision_analysis,
            created_at=row.created_at,
            expires_at=row.expires_at,
        )

    async def create(self, session_id: uuid.UUID, email: str) -> UploadRecord:
        record = UploadRecord(
            session_id=session_id,
            email=email,
            token=tokens.generate_token(),
            expires_at=tokens.new_expiry(),
        )
        async with connect() as conn:
            await conn.execute(
                sa.insert(image_uploads).values(
                    id=record.id,
                    session_id=record.session_id,
                    email=record.email,
                    token=record.token,
                    status=record.status,
                    created_at=record.created_at,
                    expires_at=record.expires_at,
                )
            )
        return record

    async def get_by_token(self, token: str) -> UploadRecord | None:
        async with connect() as conn:
            row = (
                await conn.execute(sa.select(image_uploads).where(image_uploads.c.token == token))
            ).fetchone()
            if row is None:
                return None
            record = self._row_to_record(row)
            effective = _effective_status(record)
            if effective != record.status:
                await conn.execute(
                    sa.update(image_uploads)
                    .where(image_uploads.c.token == token)
                    .values(status=effective)
                )
                record = record.model_copy(update={"status": effective})
            return record

    async def latest_for_session(self, session_id: uuid.UUID) -> UploadRecord | None:
        async with connect() as conn:
            row = (
                await conn.execute(
                    sa.select(image_uploads)
                    .where(image_uploads.c.session_id == session_id)
                    .order_by(image_uploads.c.created_at.desc())
                    .limit(1)
                )
            ).fetchone()
            if row is None:
                return None
            return await self.get_by_token(row.token)

    async def save_image(self, token: str, image_path: str) -> UploadRecord:
        async with connect() as conn:
            await conn.execute(
                sa.update(image_uploads)
                .where(image_uploads.c.token == token)
                .values(image_path=image_path, status="uploaded")
            )
        record = await self.get_by_token(token)
        assert record is not None
        return record

    async def save_analysis(self, token: str, analysis: dict[str, Any]) -> UploadRecord:
        async with connect() as conn:
            await conn.execute(
                sa.update(image_uploads)
                .where(image_uploads.c.token == token)
                .values(vision_analysis=analysis, status="analyzed")
            )
        record = await self.get_by_token(token)
        assert record is not None
        return record


_store: UploadStore = PostgresUploadStore()


def get_store() -> UploadStore:
    return _store


def set_store(store: UploadStore) -> None:
    """Test/dev hook to swap in ``InMemoryUploadStore`` (or a fake)."""
    global _store
    _store = store
