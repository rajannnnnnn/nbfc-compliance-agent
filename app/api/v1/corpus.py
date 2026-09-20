"""GET /v1/corpus — unauthenticated by design (LLD §15.3): the system's central claim is that
its findings are grounded, and this is where anyone can check it."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.config import Settings, get_settings
from app.db.engine import get_sessionmaker

router = APIRouter(prefix="/v1", tags=["corpus"])

_SNAPSHOT_SQL = """
SELECT id, created_at, embedding_model, parser_version, chunk_count
FROM corpus_snapshot WHERE is_active = true
"""

_INSTRUMENTS_SQL = """
SELECT code, official_title, circular_number, issued_on, effective_from, effective_to,
       status, citable, verification_status, verification_note, source_url, source_sha256,
       retrieved_at,
       (SELECT COUNT(*) FROM clause c WHERE c.instrument_id = ri.id) AS clause_count
FROM regulation_instrument ri WHERE snapshot_id = :sid ORDER BY code
"""

_SUPERSESSIONS_SQL = """
SELECT ri.code AS superseding, rs.superseded_circular_number, rs.superseded_title,
       rs.superseded_on
FROM regulation_supersession rs
JOIN regulation_instrument ri ON ri.id = rs.superseding_instrument_id
WHERE rs.snapshot_id = :sid
"""


@router.get("/corpus")
async def get_corpus(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    sessionmaker = get_sessionmaker(settings)
    async with sessionmaker() as session:
        snap = (await session.execute(text(_SNAPSHOT_SQL))).first()
        if snap is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": {
                        "code": "CC-503-CORPUS-UNAVAILABLE",
                        "message": "no active corpus snapshot",
                    }
                },
            )

        instruments = [
            {
                "code": row.code,
                "official_title": row.official_title,
                "circular_number": row.circular_number,
                "issued_on": row.issued_on.isoformat() if row.issued_on else None,
                "effective_from": row.effective_from.isoformat() if row.effective_from else None,
                "effective_to": row.effective_to.isoformat() if row.effective_to else None,
                "status": row.status,
                "citable": row.citable,
                "verification_status": row.verification_status,
                "verification_note": row.verification_note,
                "source_url": row.source_url,
                "source_sha256": row.source_sha256,
                "retrieved_at": row.retrieved_at.isoformat() if row.retrieved_at else None,
                "clause_count": row.clause_count,
            }
            for row in (await session.execute(text(_INSTRUMENTS_SQL), {"sid": str(snap.id)}))
        ]

        supersessions = [
            {
                "superseding": row.superseding,
                "superseded_circular_number": row.superseded_circular_number,
                "superseded_title": row.superseded_title,
                "superseded_on": row.superseded_on.isoformat(),
            }
            for row in (await session.execute(text(_SUPERSESSIONS_SQL), {"sid": str(snap.id)}))
        ]

    return {
        "snapshot_id": str(snap.id),
        "created_at": snap.created_at.isoformat(),
        "embedding_model": snap.embedding_model,
        "parser_version": snap.parser_version,
        "chunk_count": snap.chunk_count,
        "instruments": instruments,
        "supersessions": supersessions,
    }
