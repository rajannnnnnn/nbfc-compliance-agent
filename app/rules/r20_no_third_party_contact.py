"""R20 — No contact with relatives, referees, friends or colleagues to intimidate
(RBC-AMD2026/p100X)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, MissingFact, NotApplicable, RuleOutcome
from app.rules.registry import register

AMENDMENT_EFFECTIVE = date(2027, 1, 1)


@register(severity="critical")
class R20NoThirdPartyContact:
    id = "R20_no_third_party_contact"
    check_key = "R20_no_third_party_contact"
    clause_paths = ["RBC-AMD2026/p100X"]
    consumes = ["third_party_contacted_flag", "third_party_relationship"]
    valid_from = AMENDMENT_EFFECTIVE
    valid_to = None

    def evaluate(
        self,
        facts: FactIndex,
        account: LoanAccountRef,
        *,
        as_of: date,
        clause_excerpts: dict[str, str],
    ) -> RuleOutcome | NotApplicable:
        if as_of < AMENDMENT_EFFECTIVE:
            return NOT_APPLICABLE
        try:
            contacted = facts.flag_of("third_party_contacted_flag")
        except MissingFact:
            return NOT_APPLICABLE
        cite = [
            Citation(
                clause_path="RBC-AMD2026/p100X",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("RBC-AMD2026/p100X", ""),
            )
        ]
        if not contacted:
            return RuleOutcome(
                verdict="compliant",
                citations=cite,
                rationale="No third party was contacted for recovery purposes.",
                inputs_used={"third_party_contacted_flag": "false"},
            )
        relationship = (
            facts.string_of("third_party_relationship")
            if facts.has("third_party_relationship")
            else "unknown"
        )
        if relationship == "guarantor":
            return RuleOutcome(
                verdict="compliant",
                citations=cite,
                rationale="Only the borrower's guarantor was contacted, which is not prohibited third-party contact.",
                inputs_used={"third_party_relationship": relationship},
            )
        return RuleOutcome(
            verdict="violation",
            citations=cite,
            rationale=f"A third party ({relationship}) was contacted for recovery purposes.",
            inputs_used={
                "third_party_contacted_flag": "true",
                "third_party_relationship": relationship,
            },
        )
