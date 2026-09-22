"""R15 — Recovery agent's identity notified to the borrower before first contact (DL2025/p8)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, MissingFact, NotApplicable, RuleOutcome
from app.rules.registry import register


@register(severity="major")
class R15AgentIdentityNotified:
    id = "R15_agent_identity_notified"
    check_key = "R15_agent_identity_notified"
    clause_paths = ["DL2025/p8"]
    consumes = ["recovery_agent_identity_notified_before_contact_flag"]
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
        try:
            notified = facts.flag_of("recovery_agent_identity_notified_before_contact_flag")
        except MissingFact:
            return NOT_APPLICABLE
        cite = [
            Citation(
                clause_path="DL2025/p8",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("DL2025/p8", ""),
            )
        ]
        if notified:
            return RuleOutcome(
                verdict="compliant",
                citations=cite,
                rationale="Recovery agent's identity was notified to the borrower before first contact.",
                inputs_used={"recovery_agent_identity_notified_before_contact_flag": "true"},
            )
        return RuleOutcome(
            verdict="violation",
            citations=cite,
            rationale="Recovery agent's identity was not notified to the borrower before first contact.",
            inputs_used={"recovery_agent_identity_notified_before_contact_flag": "false"},
        )
