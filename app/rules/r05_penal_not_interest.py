"""R05 — Penal charge not levied as penal interest added to the rate (RBC2025/p30/1)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, MissingFact, NotApplicable, RuleOutcome
from app.rules.registry import register


@register(severity="major")
class R05PenalNotInterest:
    id = "R05_penal_not_interest"
    check_key = "R05_penal_not_interest"
    clause_paths = ["RBC2025/p30/1"]
    consumes = ["penal_charge_described_as_interest_flag"]
    valid_from = date(2025, 11, 28)
    valid_to = None

    def evaluate(
        self,
        facts: FactIndex,
        account: LoanAccountRef,
        *,
        as_of: date,
        clause_excerpts: dict[str, str],
    ) -> RuleOutcome | NotApplicable:
        if as_of < self.valid_from:
            return NOT_APPLICABLE
        try:
            described_as_interest = facts.flag_of("penal_charge_described_as_interest_flag")
        except MissingFact:
            return NOT_APPLICABLE
        cite = [
            Citation(
                clause_path="RBC2025/p30/1",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("RBC2025/p30/1", ""),
            )
        ]
        if described_as_interest:
            return RuleOutcome(
                verdict="violation",
                citations=cite,
                rationale="Penal charge is described as penal interest added to the rate of interest, which the instrument prohibits.",
                inputs_used={"penal_charge_described_as_interest_flag": "true"},
            )
        return RuleOutcome(
            verdict="compliant",
            citations=cite,
            rationale="Penal charge is not described as interest added to the rate.",
            inputs_used={"penal_charge_described_as_interest_flag": "false"},
        )
