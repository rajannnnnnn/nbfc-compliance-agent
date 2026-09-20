"""R07 — Cooling-off period disclosed, not less than one day, no prepayment penalty within it
(DL2025/p10)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, MissingFact, NotApplicable, RuleOutcome
from app.rules.registry import register

MIN_COOLING_OFF_DAYS = 1


@register(severity="major")
class R07CoolingOffDisclosed:
    id = "R07_cooling_off_disclosed"
    check_key = "R07_cooling_off_disclosed"
    clause_paths = ["DL2025/p10"]
    consumes = ["cooling_off_period_days", "cooling_off_prepayment_penalty_flag"]
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
        if not account.is_digital_lending:
            return NOT_APPLICABLE
        try:
            days = facts.int_of("cooling_off_period_days")
        except MissingFact:
            cite = [
                Citation(
                    clause_path="DL2025/p10",
                    role="decisive",
                    quoted_clause_excerpt=clause_excerpts.get("DL2025/p10", ""),
                )
            ]
            return RuleOutcome(
                verdict="violation",
                citations=cite,
                rationale="No cooling-off period is disclosed for this digital lending arrangement.",
                inputs_used={},
            )
        penalty = facts.flag_of("cooling_off_prepayment_penalty_flag", default=False)
        cite = [
            Citation(
                clause_path="DL2025/p10",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("DL2025/p10", ""),
            )
        ]
        if days < MIN_COOLING_OFF_DAYS:
            return RuleOutcome(
                verdict="violation",
                citations=cite,
                rationale=f"Disclosed cooling-off period of {days} day(s) is below the minimum of {MIN_COOLING_OFF_DAYS} day.",
                inputs_used={"cooling_off_period_days": str(days)},
            )
        if penalty:
            return RuleOutcome(
                verdict="violation",
                citations=cite,
                rationale="A prepayment penalty is levied within the disclosed cooling-off period.",
                inputs_used={
                    "cooling_off_period_days": str(days),
                    "cooling_off_prepayment_penalty_flag": "true",
                },
            )
        return RuleOutcome(
            verdict="compliant",
            citations=cite,
            rationale=f"Cooling-off period of {days} day(s) disclosed with no prepayment penalty within it.",
            inputs_used={"cooling_off_period_days": str(days)},
        )
