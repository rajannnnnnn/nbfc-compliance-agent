"""retrieve_candidates(...). LLD §8.5.

Step 7 (context_only) is what makes no_clause_found useful rather than merely honest: when
nothing applies, the analyst still sees the provision that would have applied and why it did
not — not yet in force, superseded, or (ADR-005) scoped to a different borrower class.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.corpus.pinning import expand_parent_to_descendants, load_pinning_yaml
from app.domain.clauses import ClauseCandidate, ClauseCandidateSet
from app.domain.enums import ExclusionReason
from app.retrieve.applicability import (
    APPLICABILITY_SQL,
    CONTEXT_ONLY_BORROWER_SCOPE_SQL,
    CONTEXT_ONLY_SQL_NO_DATES,
    require_as_of,
)
from app.retrieve.fusion import rrf
from app.retrieve.lexical import build_lexical_query, fts_search
from app.retrieve.vector import ann_search

# Pinned lookups go through the SAME applicability filter as vector/lexical search — a pin
# is a hint about which clause_paths are relevant to a field, never an override of temporal
# or borrower-class scoping. Without this, a pinned field (e.g. contact_datetime -> the
# amendment's own contact-hour clause) would always appear in `candidates` regardless of the
# event date, which is exactly the defect PRD §11's temporal pair is built to catch.
_PINNED_LOOKUP_SQL = f"""
SELECT c.id, c.clause_path, c.instrument_code, c.heading, c.text, c.effective_from,
       c.effective_to, c.citable
FROM clause c
JOIN regulation_instrument i ON i.id = c.instrument_id
WHERE {APPLICABILITY_SQL}
  AND c.clause_path = ANY(:paths)
"""

_ALL_PATHS_FOR_INSTRUMENT_SQL = """
SELECT clause_path FROM clause WHERE snapshot_id = :snapshot_id
"""

_REFERENCE_HOP_SQL = """
SELECT cr.to_instrument_code, cr.to_clause_path
FROM clause_reference cr
WHERE cr.snapshot_id = :snapshot_id
  AND cr.from_clause_id = ANY(:clause_ids)
  AND cr.reference_kind = 'incorporates'
"""

_HOP_CANDIDATES_SQL = """
SELECT c.id, c.clause_path, c.instrument_code, c.heading, c.text, c.effective_from,
       c.effective_to, c.citable
FROM clause c
JOIN regulation_instrument i ON i.id = c.instrument_id
WHERE c.snapshot_id = :snapshot_id
  AND c.instrument_code = :instrument_code
  AND c.citable = true AND i.citable = true AND i.status <> 'draft'
"""


async def _pinned_candidates(
    session: AsyncSession,
    *,
    snapshot_id: UUID,
    entity_type: str,
    borrower_class: str,
    as_of: date,
    field_key: str,
    pinning_path: str,
) -> tuple[list[ClauseCandidate], list[str]]:
    """Returns (applicable candidates, all expanded pinned paths) — the second element seeds
    context_only so a pinned-but-excluded clause is still surfaced with a reason rather than
    silently dropped."""
    pins = load_pinning_yaml(pinning_path)
    pinned_paths = pins.get(field_key, [])
    if not pinned_paths:
        return [], []

    all_paths_rows = await session.execute(
        text(_ALL_PATHS_FOR_INSTRUMENT_SQL), {"snapshot_id": str(snapshot_id)}
    )
    all_paths = [r[0] for r in all_paths_rows]

    expanded: list[str] = []
    for p in pinned_paths:
        expanded.extend(expand_parent_to_descendants(p, all_paths))
    expanded = list(dict.fromkeys(expanded))  # de-dupe, preserve order

    rows = await session.execute(
        text(_PINNED_LOOKUP_SQL),
        {
            "snapshot_id": str(snapshot_id),
            "entity_type": entity_type,
            "borrower_class": borrower_class,
            "as_of": as_of,
            "paths": expanded,
        },
    )
    by_path = {r.clause_path: r for r in rows}

    candidates = []
    for rank, path in enumerate(expanded, start=1):
        row = by_path.get(path)
        if row is None:
            continue
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
                source="pinned",
                rank=rank,
                score=0.0,
            )
        )
    return candidates, expanded


async def _reference_hop_candidates(
    session: AsyncSession, *, snapshot_id: UUID, seed_clause_ids: list[UUID], hops: int
) -> list[ClauseCandidate]:
    if hops < 1 or not seed_clause_ids:
        return []
    edge_rows = await session.execute(
        text(_REFERENCE_HOP_SQL),
        {"snapshot_id": str(snapshot_id), "clause_ids": [str(c) for c in seed_clause_ids]},
    )
    candidates: list[ClauseCandidate] = []
    rank = 1
    for edge in edge_rows:
        rows = await session.execute(
            text(_HOP_CANDIDATES_SQL),
            {"snapshot_id": str(snapshot_id), "instrument_code": edge.to_instrument_code},
        )
        for row in rows:
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
                    source="reference_hop",
                    rank=rank,
                    score=0.0,
                )
            )
            rank += 1
    return candidates


async def _context_only_candidates(
    session: AsyncSession,
    *,
    snapshot_id: UUID,
    entity_type: str,
    borrower_class: str,
    as_of: date,
    seed_paths: set[str],
) -> list[ClauseCandidate]:
    """Re-queries the seed paths without the date predicates (temporal exclusion) and,
    separately, without the borrower-class predicate (scope exclusion) — annotating each
    with why it was excluded. Draft/citable stay enforced throughout (ADR-012)."""
    if not seed_paths:
        return []

    out: list[ClauseCandidate] = []

    # Temporal exclusion: in the corpus, citable, entity-matched, not draft — but outside
    # the effective window, or the instrument's own window excludes it.
    rows = await session.execute(
        text(f"""
            SELECT c.id, c.clause_path, c.instrument_code, c.heading, c.text,
                   c.effective_from, c.effective_to, c.citable, i.status
            FROM clause c
            JOIN regulation_instrument i ON i.id = c.instrument_id
            WHERE {CONTEXT_ONLY_SQL_NO_DATES}
              AND c.clause_path = ANY(:paths)
            """),
        {
            "snapshot_id": str(snapshot_id),
            "entity_type": entity_type,
            "paths": list(seed_paths),
        },
    )
    for row in rows:
        in_window = (row.effective_from is None or row.effective_from <= as_of) and (
            row.effective_to is None or row.effective_to > as_of
        )
        if in_window:
            continue  # actually applicable — belongs in candidates, not context_only
        reason = (
            ExclusionReason.NOT_YET_IN_FORCE
            if (row.effective_from and row.effective_from > as_of)
            else ExclusionReason.SUPERSEDED
        )
        note = f"Not in force on {as_of.isoformat()}"
        if row.effective_from and row.effective_from > as_of:
            note = f"Not yet in force on {as_of.isoformat()}; commences {row.effective_from.isoformat()}."
        elif row.effective_to and row.effective_to <= as_of:
            note = f"Superseded as of {row.effective_to.isoformat()}, before {as_of.isoformat()}."
        out.append(
            ClauseCandidate(
                clause_id=row.id,
                clause_path=row.clause_path,
                instrument_code=row.instrument_code,
                effective_from=row.effective_from,
                effective_to=row.effective_to,
                citable=row.citable,
                heading=row.heading,
                text=row.text,
                source="pinned",
                rank=0,
                score=0.0,
                exclusion_reason=reason,
                context_note=note,
            )
        )

    # Borrower-scope exclusion: excluded ONLY by applies_to_borrower_classes.
    rows = await session.execute(
        text(f"""
            SELECT c.id, c.clause_path, c.instrument_code, c.heading, c.text,
                   c.effective_from, c.effective_to, c.citable
            FROM clause c
            JOIN regulation_instrument i ON i.id = c.instrument_id
            WHERE {CONTEXT_ONLY_BORROWER_SCOPE_SQL}
              AND c.clause_path = ANY(:paths)
            """),
        {
            "snapshot_id": str(snapshot_id),
            "entity_type": entity_type,
            "borrower_class": borrower_class,
            "as_of": as_of,
            "paths": list(seed_paths),
        },
    )
    for row in rows:
        out.append(
            ClauseCandidate(
                clause_id=row.id,
                clause_path=row.clause_path,
                instrument_code=row.instrument_code,
                effective_from=row.effective_from,
                effective_to=row.effective_to,
                citable=row.citable,
                heading=row.heading,
                text=row.text,
                source="pinned",
                rank=0,
                score=0.0,
                exclusion_reason=ExclusionReason.BORROWER_SCOPE,
                context_note=f"Scoped to a different borrower class than '{borrower_class}'.",
            )
        )

    return out


async def retrieve_candidates(
    *,
    session: AsyncSession,
    snapshot_id: UUID,
    entity_type: str,
    borrower_class: str,
    as_of: date | None,
    field_key: str,
    value_summary: str,
    field_label: str,
    field_description: str,
    query_vector: list[float] | None,
    settings: Settings,
    pinning_path: str = "app/corpus/pinning.yaml",
) -> ClauseCandidateSet:
    resolved_as_of = require_as_of(as_of)

    pinned, all_pinned_paths = await _pinned_candidates(
        session,
        snapshot_id=snapshot_id,
        entity_type=entity_type,
        borrower_class=borrower_class,
        as_of=resolved_as_of,
        field_key=field_key,
        pinning_path=pinning_path,
    )

    vector_results: list[ClauseCandidate] = []
    if query_vector is not None:
        vector_results = await ann_search(
            session,
            snapshot_id=snapshot_id,
            entity_type=entity_type,
            borrower_class=borrower_class,
            as_of=resolved_as_of,
            query_vector=query_vector,
            k=settings.retrieve_vector_k,
            ef_search=settings.hnsw_ef_search,
        )

    lexical_query = build_lexical_query(field_label, value_summary)
    lexical_results = await fts_search(
        session,
        snapshot_id=snapshot_id,
        entity_type=entity_type,
        borrower_class=borrower_class,
        as_of=resolved_as_of,
        query=lexical_query,
        k=settings.retrieve_lexical_k,
    )

    seed_ids = [c.clause_id for c in (pinned + vector_results)]
    hop_results = await _reference_hop_candidates(
        session,
        snapshot_id=snapshot_id,
        seed_clause_ids=seed_ids,
        hops=settings.follow_reference_hops,
    )

    fused = rrf(
        {
            "pinned": pinned,
            "vector": vector_results,
            "lexical": lexical_results,
            "reference_hop": hop_results,
        },
        k=settings.rrf_k,
        weights={
            "pinned": settings.rrf_weight_pinned,
            "vector": settings.rrf_weight_vector,
            "lexical": settings.rrf_weight_lexical,
            "reference_hop": 1.0,
        },
    )[: settings.retrieve_final_k]

    seed_paths = set(all_pinned_paths) | {c.clause_path for c in vector_results}
    context_only = await _context_only_candidates(
        session,
        snapshot_id=snapshot_id,
        entity_type=entity_type,
        borrower_class=borrower_class,
        as_of=resolved_as_of,
        seed_paths=seed_paths,
    )

    return ClauseCandidateSet(
        as_of=resolved_as_of,
        entity_type=entity_type,
        borrower_class=borrower_class,
        candidates=fused,
        context_only=context_only,
        snapshot_id=snapshot_id,
    )
