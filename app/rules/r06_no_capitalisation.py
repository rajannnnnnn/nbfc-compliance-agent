"""R06 — No capitalisation of penal charges (RBC2025/p30/2)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, MissingFact, NotApplicable, RuleOutcome
from app.rules.registry import register


@register(severity="major")
class R06NoCapitalisation:
    id = "R06_no_capitalisation"
    check_key = "R06_no_capitalisation"
    clause_paths = ["RBC2025/p30/2"]
    consumes = ["penal_charge_capitalised_flag"]
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
            capitalised = facts.flag_of("penal_charge_capitalised_flag")
        except MissingFact:
            return NOT_APPLICABLE
        cite = [
            Citation(
                clause_path="RBC2025/p30/2",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("RBC2025/p30/2", ""),
            )
        ]
        if capitalised:
            return RuleOutcome(
                verdict="violation",
                citations=cite,
                rationale="Penal charge has been capitalised, which the instrument prohibits.",
                inputs_used={"penal_charge_capitalised_flag": "true"},
            )
        return RuleOutcome(
            verdict="compliant",
            citations=cite,
            rationale="Penal charge has not been capitalised.",
            inputs_used={"penal_charge_capitalised_flag": "false"},
        )
