"""Every eval/cases/verdict/*.json case is meant to exercise assess_fact()'s fallthrough to
real retrieval + a real model call, never a rule decision (see docs/DECISIONS.md ADR-046).

This asserts that mechanism directly against the rule objects, with no DB and no LLM call:
given exactly the case's expected.facts (and nothing else) and its account_profile/event_date,
every rule that consumes the case's trigger field must return NotApplicable. If a case ever
regresses to a rule-decided outcome (e.g. because a rule's own preconditions change), this
test catches it — a case that no longer exercises the fallthrough path is not a verdict case.
"""

from datetime import date
from uuid import uuid4

import pytest

from app.domain.documents import LoanAccountRef
from app.rules.base import FactIndex, FactRecord, NotApplicable
from app.rules.registry import rules_for_field
from eval.loader import load_suite

CASES = load_suite("verdict")


@pytest.mark.parametrize("case", CASES, ids=[c.case_ref for c in CASES])
def test_case_trigger_field_falls_through_every_consuming_rule(case):
    trigger_field = case.expected.check_key.removeprefix("F:")
    assert case.expected.check_key.startswith("F:"), (
        f"{case.case_ref}: check_key {case.expected.check_key!r} is not a model-decided "
        "check_key (expected 'F:<field_key>') -- this suite only holds genuine fallthrough "
        "cases, not rule-decided ones."
    )
    assert (
        trigger_field in case.expected.facts
    ), f"{case.case_ref}: trigger field {trigger_field!r} must be the one fact provided"

    facts = FactIndex(
        facts={
            key: FactRecord(
                field_key=key, value_type="enum", value_normalized={"v": value}, is_absent=False
            )
            for key, value in case.expected.facts.items()
        }
    )
    account = LoanAccountRef(
        id=uuid4(),
        tenant_id=uuid4(),
        external_ref=case.case_ref,
        product_type=case.account_profile.product_type,
        is_microfinance=case.account_profile.is_microfinance,
        is_digital_lending=case.account_profile.is_digital_lending,
        device_financed=case.account_profile.device_financed,
    )
    event_date = date.fromisoformat(case.event_date)

    consuming_rules = list(rules_for_field(trigger_field))
    assert consuming_rules, f"{case.case_ref}: no registered rule consumes {trigger_field!r}"

    for rule in consuming_rules:
        outcome = rule.evaluate(facts, account, as_of=event_date, clause_excerpts={})
        assert isinstance(outcome, NotApplicable), (
            f"{case.case_ref}: {rule.id} decided this case instead of falling through "
            f"(returned {outcome!r}) -- this case no longer exercises real model judgment"
        )
