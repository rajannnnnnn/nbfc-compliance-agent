"""R25 — Grievance officer's name, email, telephone and address on recovery communications
(RBC-AMD2026/p100Y)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, NotApplicable, RuleOutcome
from app.rules.registry import register

AMENDMENT_EFFECTIVE = date(2027, 1, 1)


@register(severity="minor")
class R25GrievanceOfficerOnRecoveryComms:
    id = "R25_grievance_officer_on_recovery_comms"
    check_key = "R25_grievance_officer_on_recovery_comms"
    clause_paths = ["RBC-AMD2026/p100Y"]
    consumes = ["grievance_officer_details_disclosed_flag"]
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
        if not facts.has("grievance_officer_details_disclosed_flag"):
            return NOT_APPLICABLE
        disclosed = facts.flag_of("grievance_officer_details_disclosed_flag")
        cite = [
            Citation(
                clause_path="RBC-AMD2026/p100Y",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("RBC-AMD2026/p100Y", ""),
            )
        ]
        if disclosed:
            return RuleOutcome(
                verdict="compliant",
                citations=cite,
                rationale="Grievance officer's details are disclosed on the recovery communication.",
                inputs_used={"grievance_officer_details_disclosed_flag": "true"},
            )
        return RuleOutcome(
            verdict="violation",
            citations=cite,
            rationale="Grievance officer's details are not disclosed on the recovery communication.",
            inputs_used={"grievance_officer_details_disclosed_flag": "false"},
        )
