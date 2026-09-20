"""tsquery search with in-SQL filtering. LLD §8.3.

Lexical search carries the numeric obligations. "thirty days", "Rs 5,000", "08:00 hours" and
"six months" survive lexical matching and are frequently missed by embeddings.
"""

import re
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.clauses import ClauseCandidate
from app.retrieve.applicability import APPLICABILITY_SQL

_QUERY = f"""
SELECT c.id, c.clause_path, c.instrument_code, c.heading, c.text,
       c.effective_from, c.effective_to, c.citable,
       ts_rank_cd(c.tsv, websearch_to_tsquery('english', :q)) AS score
FROM   clause c
JOIN   regulation_instrument i ON i.id = c.instrument_id
WHERE  {APPLICABILITY_SQL}
  AND  c.tsv @@ websearch_to_tsquery('english', :q)
ORDER  BY score DESC
LIMIT  :k
"""

_NUMERIC_TOKEN_RE = re.compile(
    r"\b\d[\d,.:]*\b|\b(?:one|two|three|thirty|sixty|ninety)\b", re.IGNORECASE
)


def numeric_tokens(value_summary: str) -> list[str]:
    return _NUMERIC_TOKEN_RE.findall(value_summary)


def build_lexical_query(field_label: str, value_summary: str) -> str:
    """The lexical query includes numeric/unit tokens from the fact's value — this is why
    the two searches use different query strings (LLD §8.3)."""
    tokens = numeric_tokens(value_summary)
    if tokens:
        return f"{field_label} {' '.join(tokens)}"
    return field_label


async def fts_search(
    session: AsyncSession,
    *,
    snapshot_id: UUID,
    entity_type: str,
    borrower_class: str,
    as_of: date,
    query: str,
    k: int,
) -> list[ClauseCandidate]:
    rows = await session.execute(
        text(_QUERY),
        {
            "snapshot_id": str(snapshot_id),
            "entity_type": entity_type,
            "borrower_class": borrower_class,
            "as_of": as_of,
            "q": query,
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
                source="lexical",
                rank=rank,
                score=float(row.score),
            )
        )
    return candidates
