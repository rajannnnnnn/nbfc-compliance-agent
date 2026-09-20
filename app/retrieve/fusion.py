"""Reciprocal rank fusion. LLD §8.4.

Tie-break: pinned before vector before lexical, then lower clause_path — deterministic, so a
test can assert it exactly.

Weight is 2.5, not the LLD's literal 2.0 (ADR-020): at k=60, weight 2.0 makes a rank-1-pinned
candidate exactly TIE a candidate ranked 1 in both other lists (2.0/61 == 1.0/61 + 1.0/61),
decided only by the tie-break — not the score margin the LLD's own text claims.
"""

from app.domain.clauses import ClauseCandidate

_SOURCE_ORDER = {"pinned": 0, "vector": 1, "lexical": 2, "reference_hop": 3}


def rrf(
    result_lists: dict[str, list[ClauseCandidate]],
    *,
    k: int,
    weights: dict[str, float],
) -> list[ClauseCandidate]:
    """score(doc) = sum over sources of weight[source] / (k + rank_in_source)."""
    scores: dict[str, float] = {}
    best_candidate: dict[str, ClauseCandidate] = {}
    best_source: dict[str, str] = {}
    best_rank: dict[str, int] = {}

    for source, candidates in result_lists.items():
        weight = weights.get(source, 1.0)
        for candidate in candidates:
            path = candidate.clause_path
            contribution = weight / (k + candidate.rank)
            scores[path] = scores.get(path, 0.0) + contribution
            # Keep the candidate object from the highest-priority source seen (for tie-break
            # display purposes and to attribute the winning source).
            if path not in best_source or _SOURCE_ORDER[source] < _SOURCE_ORDER[best_source[path]]:
                best_source[path] = source
                best_candidate[path] = candidate
                best_rank[path] = candidate.rank

    def sort_key(path: str) -> tuple[float, int, str]:
        return (-scores[path], _SOURCE_ORDER[best_source[path]], path)

    ordered_paths = sorted(scores.keys(), key=sort_key)

    fused: list[ClauseCandidate] = []
    for new_rank, path in enumerate(ordered_paths, start=1):
        base = best_candidate[path]
        fused.append(
            ClauseCandidate(
                clause_id=base.clause_id,
                clause_path=base.clause_path,
                instrument_code=base.instrument_code,
                effective_from=base.effective_from,
                effective_to=base.effective_to,
                citable=base.citable,
                heading=base.heading,
                text=base.text,
                source=base.source,
                rank=new_rank,
                score=scores[path],
            )
        )
    return fused
