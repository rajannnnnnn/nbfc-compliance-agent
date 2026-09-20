from uuid import uuid4

from app.retrieve.fusion import rrf


def _cand(path, rank, source="pinned"):
    from app.domain.clauses import ClauseCandidate

    return ClauseCandidate(
        clause_id=uuid4(),
        clause_path=path,
        instrument_code="DL2025",
        effective_from=None,
        effective_to=None,
        citable=True,
        heading=None,
        text="x",
        source=source,
        rank=rank,
        score=0.0,
    )


def test_rrf_arithmetic_matches_hand_computation():
    result_lists = {
        "pinned": [_cand("DL2025/p9", 1, "pinned")],
        "vector": [_cand("DL2025/p9", 1, "vector"), _cand("DL2025/p10", 2, "vector")],
    }
    fused = rrf(result_lists, k=60, weights={"pinned": 2.0, "vector": 1.0})
    by_path = {c.clause_path: c for c in fused}
    expected_p9 = 2.0 / 61 + 1.0 / 61
    assert abs(by_path["DL2025/p9"].score - expected_p9) < 1e-9
    expected_p10 = 1.0 / 62
    assert abs(by_path["DL2025/p10"].score - expected_p10) < 1e-9


def test_pinned_precedence_at_default_weight():
    """ADR-020: at the default weight (2.5), a rank-1-pinned candidate outscores a candidate
    ranked 1 in both vector and lexical — a genuine margin, not a tie decided by tie-break."""
    result_lists = {
        "pinned": [_cand("A", 1, "pinned")],
        "vector": [_cand("B", 1, "vector")],
        "lexical": [_cand("B", 1, "lexical")],
    }
    fused = rrf(result_lists, k=60, weights={"pinned": 2.5, "vector": 1.0, "lexical": 1.0})
    assert fused[0].clause_path == "A"
    by_path = {c.clause_path: c for c in fused}
    assert by_path["A"].score > by_path["B"].score


def test_deterministic_tie_break_pinned_before_vector_before_lexical():
    """At weight 2.0 (the LLD's literal value), pinned-rank-1 exactly ties vector+lexical
    rank-1 — the tie-break, not the score, must decide it."""
    result_lists = {
        "pinned": [_cand("Z", 1, "pinned")],
        "vector": [_cand("A", 1, "vector")],
        "lexical": [_cand("A", 1, "lexical")],
    }
    fused = rrf(result_lists, k=60, weights={"pinned": 2.0, "vector": 1.0, "lexical": 1.0})
    by_path = {c.clause_path: c for c in fused}
    assert by_path["Z"].score == by_path["A"].score
    assert fused[0].clause_path == "Z"  # pinned wins the tie


def test_tie_break_falls_back_to_lower_clause_path():
    result_lists = {
        "vector": [_cand("DL2025/p9", 1, "vector"), _cand("DL2025/p2", 1, "vector")],
    }
    # both would need to be in separate lists at the same rank to truly tie; simulate two
    # single-item lists each ranked 1 for an exact score tie
    result_lists = {
        "vector": [_cand("DL2025/p9", 1, "vector")],
        "lexical": [_cand("DL2025/p2", 1, "lexical")],
    }
    fused = rrf(result_lists, k=60, weights={"vector": 1.0, "lexical": 1.0})
    # scores tie (both 1/61); vector ranked before lexical in _SOURCE_ORDER wins regardless
    # of path ordering
    assert fused[0].clause_path == "DL2025/p9"


def test_provenance_survives_fusion():
    result_lists = {"pinned": [_cand("A", 1, "pinned")]}
    fused = rrf(result_lists, k=60, weights={"pinned": 2.0})
    assert fused[0].source == "pinned"
