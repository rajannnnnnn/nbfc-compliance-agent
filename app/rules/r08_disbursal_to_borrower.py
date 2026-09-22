"""R08 — Disbursal credited to the borrower's own account (DL2025/p9/i)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, MissingFact, NotApplicable, RuleOutcome
from app.rules.registry import register


@register(severity="critical")
class R08DisbursalToBorrower:
    id = "R08_disbursal_to_borrower"
    check_key = "R08_disbursal_to_borrower"
    clause_paths = ["DL2025/p9/i"]
    consumes = ["disbursal_credited_account_type"]
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
            account_type = facts.string_of("disbursal_credited_account_type")
        except MissingFact:
            return NOT_APPLICABLE
        cite = [
            Citation(
                clause_path="DL2025/p9/i",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("DL2025/p9/i", ""),
            )
        ]
        if account_type == "borrower_own":
            return RuleOutcome(
                verdict="compliant",
                citations=cite,
                rationale="Disbursal was credited to the borrower's own account.",
                inputs_used={"disbursal_credited_account_type": account_type},
            )
        return RuleOutcome(
            verdict="violation",
            citations=cite,
            rationale=f"Disbursal was credited to a {account_type.replace('_', ' ')} account rather than the borrower's own account.",
            inputs_used={"disbursal_credited_account_type": account_type},
        )
