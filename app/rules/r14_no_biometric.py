"""R14 — No biometric data collected or stored absent statutory mandate (DL2025/p13)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import FactIndex, NotApplicable, RuleOutcome
from app.rules.registry import register


@register(severity="major")
class R14NoBiometric:
    id = "R14_no_biometric"
    check_key = "R14_no_biometric"
    clause_paths = ["DL2025/p13"]
    consumes = ["biometric_data_collected_flag"]
    valid_from = None
    valid_to = None

    def evaluate(
        self,
        facts: FactIndex,
        account: LoanAccountRef,
        *,
        as_of: date,
        clause_excerpts: dict[str, str],
    ) -> RuleOutcome | NotApplicable:
        collected = facts.flag_of("biometric_data_collected_flag", default=False)
        cite = [
            Citation(
                clause_path="DL2025/p13",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("DL2025/p13", ""),
            )
        ]
        if collected:
            return RuleOutcome(
                verdict="violation",
                citations=cite,
                rationale="Biometric data is collected without a disclosed statutory mandate.",
                inputs_used={"biometric_data_collected_flag": "true"},
            )
        return RuleOutcome(
            verdict="compliant",
            citations=cite,
            rationale="No biometric data collection is on record.",
            inputs_used={"biometric_data_collected_flag": "false"},
        )
