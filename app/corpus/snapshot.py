"""Snapshot creation, activation, drift comparison. LLD §6.6.

Ingest writes a new snapshot with is_active=false; activation is two statements (deactivate
then activate), not one UPDATE...CASE, because a single statement can transiently violate the
partial unique index `uq_snapshot_active` (see M1-T08 in TASKS.md).
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class InstrumentManifestEntry(BaseModel):
    code: str
    official_title: str
    circular_number: str | None
    issued_on: date | None
    effective_from: date | None
    effective_to: date | None
    status: str
    citable: bool
    verification_status: str
    verification_note: str | None
    source_url: str
    source_sha256: str
    retrieved_at: datetime
    parser_version: str
    clause_count: int


class IngestReport(BaseModel):
    snapshot_id: UUID
    parser_version: str
    embedding_model: str
    embedding_dimension: int
    chunk_count: int
    instruments: list[InstrumentManifestEntry]
    warnings_by_instrument: dict[str, list[str]]
    reference_edges: list[dict[str, str]]
    detected_para_range_by_instrument: dict[str, tuple[str, str]]


class DriftEntry(BaseModel):
    code: str
    status: str  # "unchanged" | "changed" | "unreachable"
    old_sha256: str
    new_sha256: str | None


class DriftReport(BaseModel):
    entries: list[DriftEntry]

    @property
    def any_changed(self) -> bool:
        return any(e.status != "unchanged" for e in self.entries)


async def activate_snapshot(session: AsyncSession, snapshot_id: UUID) -> None:
    """Two statements, not one UPDATE ... CASE — see module docstring. Runs inside the
    caller's transaction so the two statements commit atomically together."""
    await session.execute(
        text("UPDATE corpus_snapshot SET is_active = false WHERE is_active = true")
    )
    await session.execute(
        text("UPDATE corpus_snapshot SET is_active = true WHERE id = :id"), {"id": str(snapshot_id)}
    )


async def get_active_snapshot_id(session: AsyncSession) -> UUID | None:
    row = await session.execute(text("SELECT id FROM corpus_snapshot WHERE is_active = true"))
    result = row.scalar_one_or_none()
    return UUID(str(result)) if result else None
