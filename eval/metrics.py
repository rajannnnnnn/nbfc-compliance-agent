"""Verdict-stage metric formulas, exact per LLD §17.2. Extraction- and retrieval-stage
metrics are not implemented — no `extraction_core`/`retrieval` suite cases exist yet for
this harness pass (see eval/loader.py's own note)."""

from dataclasses import dataclass

from eval.loader import EvalCase
from eval.runner import CaseOutcome


@dataclass
class VerdictMetrics:
    verdict_accuracy: float
    citation_validity: float
    hallucinated_citation_rate: float
    abstention_correctness: float
    false_violation_rate: float
    case_count: int


def compute_verdict_metrics(cases: list[EvalCase], outcomes: list[CaseOutcome]) -> VerdictMetrics:
    n = len(cases)
    if n == 0:
        raise ValueError("cannot compute metrics over zero cases")

    correct = sum(
        1 for c, o in zip(cases, outcomes, strict=True) if o.verdict == c.expected.verdict
    )

    total_persisted_citations = 0
    valid_citations = 0
    hallucinated_citations = 0
    for o in outcomes:
        for cite in o.persisted_citations:
            total_persisted_citations += 1
            if cite.resolves_to_live_in_window_clause:
                valid_citations += 1
            if cite.is_hallucinated:
                hallucinated_citations += 1

    expected_no_clause = [c for c in cases if c.expected.verdict == "no_clause_found"]
    correct_abstentions = sum(
        1
        for c, o in zip(cases, outcomes, strict=True)
        if c.expected.verdict == "no_clause_found" and o.verdict == "no_clause_found"
    )

    false_violations = sum(
        1
        for c, o in zip(cases, outcomes, strict=True)
        if c.expected.verdict in ("compliant", "no_clause_found") and o.verdict == "violation"
    )

    return VerdictMetrics(
        verdict_accuracy=correct / n,
        citation_validity=(
            valid_citations / total_persisted_citations if total_persisted_citations else 1.0
        ),
        hallucinated_citation_rate=(
            hallucinated_citations / total_persisted_citations if total_persisted_citations else 0.0
        ),
        abstention_correctness=(
            correct_abstentions / len(expected_no_clause) if expected_no_clause else 1.0
        ),
        false_violation_rate=false_violations / n,
        case_count=n,
    )
