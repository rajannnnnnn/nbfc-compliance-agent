"""R12 — 30-day reply window and escalation route disclosed (DL2025/p11)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import FactIndex, NotApplicable, RuleOutcome
from app.rules.registry import register


@register(severity="minor")
class R12GrievanceEscalationDisclosed:
    id = "R12_grievance_escalation_disclosed"
    check_key = "R12_grievance_escalation_disclosed"
    clause_paths = ["DL2025/p11"]
    consumes = ["grievance_mechanism_clause_ref"]
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
        disclosed = facts.has("grievance_mechanism_clause_ref")
        cite = [
            Citation(
                clause_path="DL2025/p11",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("DL2025/p11", ""),
            )
        ]
        if disclosed:
            return RuleOutcome(
                verdict="compliant",
                citations=cite,
                rationale="A grievance escalation mechanism is disclosed in the document set.",
                inputs_used={"grievance_mechanism_clause_ref": "present"},
            )
        return RuleOutcome(
            verdict="violation",
            citations=cite,
            rationale="No grievance escalation mechanism or 30-day reply window is disclosed.",
            inputs_used={"grievance_mechanism_clause_ref": "absent"},
        )
