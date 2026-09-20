"""R11 — Grievance officer's phone and email present in the KFS (DL2025/p11)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import FactIndex, NotApplicable, RuleOutcome
from app.rules.registry import register


@register(severity="minor")
class R11GrievanceOfficerInKfs:
    id = "R11_grievance_officer_in_kfs"
    check_key = "R11_grievance_officer_in_kfs"
    clause_paths = ["DL2025/p11"]
    consumes = ["grievance_officer_phone", "grievance_officer_email"]
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
        has_phone = facts.has("grievance_officer_phone")
        has_email = facts.has("grievance_officer_email")
        cite = [
            Citation(
                clause_path="DL2025/p11",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("DL2025/p11", ""),
            )
        ]
        if has_phone and has_email:
            return RuleOutcome(
                verdict="compliant",
                citations=cite,
                rationale="Grievance officer's phone and email are both present in the KFS.",
                inputs_used={
                    "grievance_officer_phone": "present",
                    "grievance_officer_email": "present",
                },
            )
        missing = []
        if not has_phone:
            missing.append("phone")
        if not has_email:
            missing.append("email")
        return RuleOutcome(
            verdict="violation",
            citations=cite,
            rationale=f"Grievance officer's {' and '.join(missing)} missing from the KFS.",
            inputs_used={"missing": ",".join(missing)},
        )
