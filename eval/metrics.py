"""Verdict- and extraction-stage metric formulas, per LLD §17.2. Retrieval-stage metrics are
not implemented — no `retrieval` suite cases exist yet for this harness pass (see
eval/loader.py's own note)."""

from dataclasses import dataclass, field

from eval.loader import EvalCase
from eval.runner import CaseOutcome, ConflictOutcome, EndToEndOutcome, ExtractionOutcome


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


@dataclass
class ExtractionMetrics:
    """LLD §17.2's extraction-stage formulas.

    `field_accuracy`: over (field, case) pairs where the field is expected present, the
    fraction where extraction also reported it present AND the normalised value matches.
    `absence_accuracy`: over all (field, case) pairs, the fraction where "extracted present"
    agrees with "expected present" (a false absence and a false presence both count against
    it, symmetrically). `span_grounding`: over (field, case) pairs that are both expected
    present and correctly extracted, the fraction whose quoted span verified against the
    source text — a correct value with no verifiable span is a real (if smaller) defect,
    tracked separately from getting the value wrong outright.
    """

    field_accuracy: float
    absence_accuracy: float
    span_grounding: float
    per_field: dict[str, dict[str, float]] = field(default_factory=dict)
    case_count: int = 0


def compute_extraction_metrics(outcomes: list[ExtractionOutcome]) -> ExtractionMetrics:
    n = len(outcomes)
    if n == 0:
        raise ValueError("cannot compute metrics over zero cases")

    per_field_totals: dict[str, dict[str, int]] = {}

    total_expected_present = 0
    total_field_accuracy_hits = 0
    total_absence_agreements = 0
    total_pairs = 0
    total_correct_present = 0
    total_span_grounded = 0

    for outcome in outcomes:
        for fo in outcome.fields:
            totals = per_field_totals.setdefault(
                fo.field_key,
                {"expected_present": 0, "field_accuracy_hits": 0, "pairs": 0, "absence_agree": 0},
            )
            totals["pairs"] += 1
            total_pairs += 1
            agree = fo.expected_present == fo.actual_present
            if agree:
                totals["absence_agree"] += 1
                total_absence_agreements += 1

            if fo.expected_present:
                totals["expected_present"] += 1
                total_expected_present += 1
                correct = fo.actual_present and fo.value_match
                if correct:
                    totals["field_accuracy_hits"] += 1
                    total_field_accuracy_hits += 1
                    total_correct_present += 1
                    if fo.span_verified:
                        total_span_grounded += 1

    per_field: dict[str, dict[str, float]] = {}
    for field_key, totals in per_field_totals.items():
        per_field[field_key] = {
            "exact_match": (
                totals["field_accuracy_hits"] / totals["expected_present"]
                if totals["expected_present"]
                else 1.0
            ),
            "absence_accuracy": totals["absence_agree"] / totals["pairs"],
        }

    return ExtractionMetrics(
        field_accuracy=(
            total_field_accuracy_hits / total_expected_present if total_expected_present else 1.0
        ),
        absence_accuracy=total_absence_agreements / total_pairs if total_pairs else 1.0,
        span_grounding=(
            total_span_grounded / total_correct_present if total_correct_present else 1.0
        ),
        per_field=per_field,
        case_count=n,
    )


@dataclass
class ConflictMetrics:
    conflict_detection_accuracy: float
    raises_check_accuracy: float
    case_count: int


def compute_conflict_metrics(
    cases: list[EvalCase], outcomes: list[ConflictOutcome]
) -> ConflictMetrics:
    n = len(cases)
    if n == 0:
        raise ValueError("cannot compute metrics over zero cases")
    for c in cases:
        if c.conflict_expected is None:
            raise ValueError(f"{c.case_ref}: conflicts-stage case requires conflict_expected")

    correct_detection = sum(
        1
        for c, o in zip(cases, outcomes, strict=True)
        if o.conflict_detected == c.conflict_expected.conflict_expected  # type: ignore[union-attr]
    )

    cases_naming_check = [
        c for c in cases if c.conflict_expected.raises_check is not None  # type: ignore[union-attr]
    ]
    correct_checks = sum(
        1
        for c, o in zip(cases, outcomes, strict=True)
        if c.conflict_expected.raises_check is not None  # type: ignore[union-attr]
        and c.conflict_expected.raises_check in o.raises_checks  # type: ignore[union-attr]
    )
    raises_check_accuracy = correct_checks / len(cases_naming_check) if cases_naming_check else 1.0

    return ConflictMetrics(
        conflict_detection_accuracy=correct_detection / n,
        raises_check_accuracy=raises_check_accuracy,
        case_count=n,
    )


@dataclass
class EndToEndMetrics:
    state_match_accuracy: float
    case_count: int


def compute_end_to_end_metrics(
    outcomes: list[EndToEndOutcome],
) -> EndToEndMetrics:
    n = len(outcomes)
    if n == 0:
        raise ValueError("cannot compute metrics over zero cases")
    correct = sum(1 for o in outcomes if o.passed)
    return EndToEndMetrics(state_match_accuracy=correct / n, case_count=n)
