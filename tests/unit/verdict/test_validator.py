from datetime import date
from uuid import uuid4

from app.domain.clauses import ClauseCandidate, ClauseCandidateSet
from app.domain.verdicts import Citation, VerdictDraft
from app.verdict.validator import is_literal_substring, validate

SNAPSHOT_ID = uuid4()


def _candidate(
    path: str,
    text: str = "The lender shall release all original documents within 30 days.",
    *,
    citable: bool = True,
    effective_from: date | None = date(2025, 1, 1),
    effective_to: date | None = None,
) -> ClauseCandidate:
    return ClauseCandidate(
        clause_id=uuid4(),
        clause_path=path,
        instrument_code=path.split("/")[0],
        effective_from=effective_from,
        effective_to=effective_to,
        citable=citable,
        heading=None,
        text=text,
        source="vector",
        rank=1,
        score=1.0,
    )


def _candidate_set(
    candidates: list[ClauseCandidate], context_only: list[ClauseCandidate] | None = None
):
    return ClauseCandidateSet(
        as_of=date(2026, 1, 1),
        entity_type="nbfc",
        borrower_class="general",
        candidates=candidates,
        context_only=context_only or [],
        snapshot_id=SNAPSHOT_ID,
    )


def _draft(verdict: str, citations: list[Citation]) -> VerdictDraft:
    return VerdictDraft(
        verdict=verdict, citations=citations, rationale="because", confidence_band="high"
    )


def test_literal_substring_whitespace_normalised():
    assert is_literal_substring("release all\n  original", "shall release all original docs")


def test_literal_substring_rejects_paraphrase():
    assert not is_literal_substring("hand back the papers", "shall release all original docs")


def test_path_not_offered_is_rejected():
    cset = _candidate_set([_candidate("RBC2025/p35")])
    draft = _draft(
        "violation",
        [
            Citation(
                clause_path="RBC2025/p99",
                role="decisive",
                quoted_clause_excerpt="release all original documents within 30 days",
            )
        ],
    )
    outcome = validate(draft, cset, as_of=date(2026, 1, 1))
    assert outcome.verdict == "no_clause_found"
    assert outcome.downgraded
    assert outcome.reason == "no_valid_decisive_citation"
    assert outcome.rejected[0].reason == "not_offered"


def test_not_citable_is_rejected():
    cset = _candidate_set([_candidate("RBC2025/p35", citable=False)])
    draft = _draft(
        "violation",
        [
            Citation(
                clause_path="RBC2025/p35",
                role="decisive",
                quoted_clause_excerpt="release all original documents within 30 days",
            )
        ],
    )
    outcome = validate(draft, cset, as_of=date(2026, 1, 1))
    assert outcome.verdict == "no_clause_found"
    assert outcome.rejected[0].reason == "not_citable"


def test_effective_from_after_as_of_is_rejected():
    cset = _candidate_set([_candidate("RBC2025/p35", effective_from=date(2027, 1, 1))])
    draft = _draft(
        "violation",
        [
            Citation(
                clause_path="RBC2025/p35",
                role="decisive",
                quoted_clause_excerpt="release all original documents within 30 days",
            )
        ],
    )
    outcome = validate(draft, cset, as_of=date(2026, 1, 1))
    assert outcome.rejected[0].reason == "not_in_force"


def test_effective_to_at_or_before_as_of_is_rejected():
    cset = _candidate_set([_candidate("RBC2025/p35", effective_to=date(2026, 1, 1))])
    draft = _draft(
        "violation",
        [
            Citation(
                clause_path="RBC2025/p35",
                role="decisive",
                quoted_clause_excerpt="release all original documents within 30 days",
            )
        ],
    )
    outcome = validate(draft, cset, as_of=date(2026, 1, 1))
    assert outcome.rejected[0].reason == "not_in_force"


def test_fabricated_excerpt_is_rejected():
    cset = _candidate_set([_candidate("RBC2025/p35")])
    draft = _draft(
        "violation",
        [
            Citation(
                clause_path="RBC2025/p35",
                role="decisive",
                quoted_clause_excerpt="this text does not appear in the clause at all",
            )
        ],
    )
    outcome = validate(draft, cset, as_of=date(2026, 1, 1))
    assert outcome.verdict == "no_clause_found"
    assert outcome.rejected[0].reason == "excerpt_not_substring"


def test_context_only_excerpt_is_also_verified_adr025():
    """SQ-18/ADR-025: a context_only citation with a fabricated excerpt must be rejected too,
    not silently kept because it was never checked."""
    ctx = _candidate("RBC-AMD2026/p100W", text="only between 08:00 hours and 19:00 hours")
    cset = _candidate_set([], context_only=[ctx])
    draft = _draft(
        "no_clause_found",
        [
            Citation(
                clause_path="RBC-AMD2026/p100W",
                role="context_only",
                quoted_clause_excerpt="a sentence invented by the model, not in the clause",
            )
        ],
    )
    outcome = validate(draft, cset, as_of=date(2026, 1, 1))
    assert outcome.verdict == "no_clause_found"
    assert not outcome.downgraded
    assert outcome.citations == []
    assert outcome.rejected[0].reason == "excerpt_not_substring"


def test_context_only_with_genuine_excerpt_is_kept():
    ctx = _candidate("RBC-AMD2026/p100W", text="only between 08:00 hours and 19:00 hours")
    cset = _candidate_set([], context_only=[ctx])
    draft = _draft(
        "no_clause_found",
        [
            Citation(
                clause_path="RBC-AMD2026/p100W",
                role="context_only",
                quoted_clause_excerpt="only between 08:00 hours and 19:00 hours",
            )
        ],
    )
    outcome = validate(draft, cset, as_of=date(2026, 1, 1))
    assert outcome.verdict == "no_clause_found"
    assert len(outcome.citations) == 1
    assert not outcome.downgraded


def test_conclusive_verdict_with_zero_decisive_downgrades():
    cset = _candidate_set([_candidate("RBC2025/p35")])
    draft = _draft("compliant", [])
    outcome = validate(draft, cset, as_of=date(2026, 1, 1))
    assert outcome.verdict == "no_clause_found"
    assert outcome.downgraded
    assert outcome.reason == "no_valid_decisive_citation"


def test_ambiguous_with_one_decisive_records_reason():
    cset = _candidate_set(
        [_candidate("RBC2025/p35"), _candidate("RBC2025/p36", "a different clause entirely")]
    )
    draft = _draft(
        "ambiguous",
        [
            Citation(
                clause_path="RBC2025/p35",
                role="decisive",
                quoted_clause_excerpt="release all original documents within 30 days",
            )
        ],
    )
    outcome = validate(draft, cset, as_of=date(2026, 1, 1))
    assert outcome.verdict == "ambiguous"
    assert not outcome.downgraded
    assert outcome.reason == "single_decisive_citation_recorded"


def test_no_clause_found_with_decisive_citations_demotes_to_context():
    cset = _candidate_set([_candidate("RBC2025/p35")])
    draft = _draft(
        "no_clause_found",
        [
            Citation(
                clause_path="RBC2025/p35",
                role="decisive",
                quoted_clause_excerpt="release all original documents within 30 days",
            )
        ],
    )
    outcome = validate(draft, cset, as_of=date(2026, 1, 1))
    assert outcome.verdict == "no_clause_found"
    assert outcome.downgraded
    assert outcome.reason == "abstention_with_citations"
    assert outcome.citations[0].role == "context_only"


def test_clean_conclusive_verdict_passes_through():
    cset = _candidate_set([_candidate("RBC2025/p35")])
    draft = _draft(
        "violation",
        [
            Citation(
                clause_path="RBC2025/p35",
                role="decisive",
                quoted_clause_excerpt="release all original documents within 30 days",
            )
        ],
    )
    outcome = validate(draft, cset, as_of=date(2026, 1, 1))
    assert outcome.verdict == "violation"
    assert not outcome.downgraded
    assert outcome.reason is None
    assert len(outcome.citations) == 1
