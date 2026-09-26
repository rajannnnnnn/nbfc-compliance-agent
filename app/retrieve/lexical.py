"""tsquery search with in-SQL filtering. LLD §8.3.

Lexical search carries the numeric obligations. "thirty days", "Rs 5,000", "08:00 hours" and
"six months" survive lexical matching and are frequently missed by embeddings.

Queries use whichever text search configuration `clause.tsv` was actually generated with
(migration 0010, ADR-037): `clausecheck_en` on a Postgres that could install the
`numbers_syn` synonym dictionary (self-hosted, `scripts/tsearch/numbers.syn` mounted), or
plain `'english'` on managed Postgres (Neon, RDS, Supabase, ...), which gives no filesystem
access for that file — the migration's own `upgrade()` falls back silently in that case. This
module must resolve the *same* fallback at query time, not hardcode `clausecheck_en`: querying
with a config name Postgres doesn't have raises `UndefinedObjectError` for every single lexical
call, which is a hard failure of `assess.document` (confirmed in production against Neon,
2026-09-26) — not a slow LLM, a crash on the very first retrieval.
"""

import re
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.clauses import ClauseCandidate
from app.retrieve.applicability import APPLICABILITY_SQL

_TS_CONFIG_EXISTS_SQL = "SELECT 1 FROM pg_catalog.pg_ts_config WHERE cfgname = :cfg"

_resolved_ts_config: str | None = None


async def resolve_ts_config(session: AsyncSession) -> str:
    """Mirrors migration 0010's own upgrade() fallback: `clausecheck_en` if this Postgres
    actually has it, otherwise plain `'english'`. Cached per process — the answer is a
    property of the deployment target, not of any single request."""
    global _resolved_ts_config
    if _resolved_ts_config is None:
        row = (
            await session.execute(text(_TS_CONFIG_EXISTS_SQL), {"cfg": "clausecheck_en"})
        ).first()
        _resolved_ts_config = "clausecheck_en" if row is not None else "english"
    return _resolved_ts_config


_QUERY = f"""
SELECT c.id, c.clause_path, c.instrument_code, c.heading, c.text,
       c.effective_from, c.effective_to, c.citable,
       ts_rank_cd(c.tsv, websearch_to_tsquery(CAST(:tscfg AS regconfig), :q)) AS score
FROM   clause c
JOIN   regulation_instrument i ON i.id = c.instrument_id
WHERE  {APPLICABILITY_SQL}
  AND  c.tsv @@ websearch_to_tsquery(CAST(:tscfg AS regconfig), :q)
ORDER  BY score DESC
LIMIT  :k
"""

_NUMBER_WORDS = (
    "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    "thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    "twenty|twenty-four|thirty|forty|fifty|sixty|seventy|eighty|ninety"
)
_NUMERIC_TOKEN_RE = re.compile(rf"\b\d[\d,.:]*\b|\b(?:{_NUMBER_WORDS})\b", re.IGNORECASE)


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
    tscfg = await resolve_ts_config(session)
    rows = await session.execute(
        text(_QUERY),
        {
            "snapshot_id": str(snapshot_id),
            "entity_type": entity_type,
            "borrower_class": borrower_class,
            "as_of": as_of,
            "q": query,
            "k": k,
            "tscfg": tscfg,
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
