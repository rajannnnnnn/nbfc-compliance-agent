"""R24 — ₹250 per hour compensation for wrongful delay in restoration (RBC-AMD2026/p100S)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, MissingFact, NotApplicable, RuleOutcome
from app.rules.registry import register

AMENDMENT_EFFECTIVE = date(2027, 1, 1)
MAX_REASONABLE_HOURS = 0  # any wrongful delay hours recorded imply compensation is owed


@register(severity="major")
class R24RestorationCompensation:
    id = "R24_restoration_compensation"
    check_key = "R24_restoration_compensation"
    clause_paths = ["RBC-AMD2026/p100S"]
    consumes = ["device_restoration_delay_hours"]
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
            delay_hours = facts.int_of("device_restoration_delay_hours")
        except MissingFact:
            return NOT_APPLICABLE
        cite = [
            Citation(
                clause_path="RBC-AMD2026/p100S",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("RBC-AMD2026/p100S", ""),
            )
        ]
        if delay_hours <= MAX_REASONABLE_HOURS:
            return RuleOutcome(
                verdict="compliant",
                citations=cite,
                rationale="No wrongful delay in device restoration is on record.",
                inputs_used={"device_restoration_delay_hours": str(delay_hours)},
            )
        owed_paise = delay_hours * 25_000  # Rs 250/hour
        return RuleOutcome(
            verdict="violation",
            citations=cite,
            rationale=f"Device restoration was wrongfully delayed by {delay_hours} hour(s); Rs {owed_paise // 100} owed in compensation.",
            inputs_used={
                "device_restoration_delay_hours": str(delay_hours),
                "owed_paise": str(owed_paise),
            },
        )
