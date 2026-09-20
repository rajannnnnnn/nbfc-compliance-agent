from eval.loader import EvalCase
from eval.metrics import compute_verdict_metrics
from eval.runner import CaseOutcome, PersistedCitationCheck


def _case(check_key: str, verdict: str) -> EvalCase:
    return EvalCase.model_validate(
        {
            "case_ref": "X",
            "suite": "numeric_rules",
            "stage": "verdict",
            "doc_type": "kfs",
            "event_date": "2026-01-01",
            "account_profile": {"product_type": "personal"},
            "expected": {"check_key": check_key, "verdict": verdict},
        }
    )


def test_verdict_accuracy_and_false_violation_rate():
    cases = [_case("F:a", "compliant"), _case("F:b", "violation")]
    outcomes = [
        CaseOutcome(case_ref="X", verdict="violation", check_key="F:a"),  # wrong: false violation
        CaseOutcome(case_ref="X", verdict="violation", check_key="F:b"),  # correct
    ]
    m = compute_verdict_metrics(cases, outcomes)
    assert m.verdict_accuracy == 0.5
    assert m.false_violation_rate == 0.5


def test_abstention_correctness_only_over_expected_no_clause_cases():
    cases = [_case("F:a", "no_clause_found"), _case("F:b", "violation")]
    outcomes = [
        CaseOutcome(case_ref="X", verdict="no_clause_found", check_key="F:a"),
        CaseOutcome(case_ref="X", verdict="violation", check_key="F:b"),
    ]
    m = compute_verdict_metrics(cases, outcomes)
    assert m.abstention_correctness == 1.0


def test_hallucinated_citation_rate_over_persisted_citations():
    cases = [_case("F:a", "violation")]
    outcomes = [
        CaseOutcome(
            case_ref="X",
            verdict="violation",
            check_key="F:a",
            persisted_citations=[
                PersistedCitationCheck("P/p1", "decisive", True, False),
                PersistedCitationCheck("P/p2", "context_only", False, True),
            ],
        )
    ]
    m = compute_verdict_metrics(cases, outcomes)
    assert m.hallucinated_citation_rate == 0.5
    assert m.citation_validity == 0.5


def test_no_persisted_citations_defaults_do_not_crash():
    cases = [_case("F:a", "no_clause_found")]
    outcomes = [CaseOutcome(case_ref="X", verdict="no_clause_found", check_key="F:a")]
    m = compute_verdict_metrics(cases, outcomes)
    assert m.hallucinated_citation_rate == 0.0
    assert m.citation_validity == 1.0
