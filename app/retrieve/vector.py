"""pgvector ANN search with in-SQL filtering. LLD §8.2.

Skips clauses with no embedding (the placeholder corpus has none until an embedding key is
configured — ADR-001/ADR-004) rather than erroring on a NULL <=> comparison.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.clauses import ClauseCandidate
from app.retrieve.applicability import APPLICABILITY_SQL

_QUERY = f"""
SELECT c.id, c.clause_path, c.instrument_code, c.heading, c.text,
       c.effective_from, c.effective_to, c.citable,
       1 - (c.embedding <=> :qvec) AS score
FROM   clause c
JOIN   regulation_instrument i ON i.id = c.instrument_id
WHERE  c.embedding IS NOT NULL
  AND  {APPLICABILITY_SQL}
ORDER  BY c.embedding <=> :qvec
LIMIT  :k
"""


async def ann_search(
    session: AsyncSession,
    *,
    snapshot_id: UUID,
    entity_type: str,
    borrower_class: str,
    as_of: date,
    query_vector: list[float],
    k: int,
    ef_search: int = 120,
) -> list[ClauseCandidate]:
    await session.execute(text(f"SET LOCAL hnsw.ef_search = {int(ef_search)}"))
    rows = await session.execute(
        text(_QUERY),
        {
            "snapshot_id": str(snapshot_id),
            "entity_type": entity_type,
            "borrower_class": borrower_class,
            "as_of": as_of,
            "qvec": str(query_vector),
            "k": k,
        },
    )
    candidates = []
    for rank, row in enumerate(rows, start=1):
        candidates.append(
            ClauseCandidate(
                clause_id=row.id,
                clause_path=row.clause_path,
                instrument_code=row.instrument_code,
                effective_from=row.effective_from,
                effective_to=row.effective_to,
                citable=row.citable,
                heading=row.heading,
                text=row.text,
                source="vector",
                rank=rank,
                score=float(row.score),
            )
        )
    return candidates


def build_query_text(field_label: str, description_first_sentence: str, value_summary: str) -> str:
    """LLD §8.2: 'the field's human label and its registry description retrieve far better
    than the bare key.'"""
    return f"{field_label}. {description_first_sentence}. Value context: {value_summary}"
