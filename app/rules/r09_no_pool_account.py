"""R09 — Repayment direct to the lender, no third-party pool account (DL2025/p9/ii)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, MissingFact, NotApplicable, RuleOutcome
from app.rules.registry import register


@register(severity="critical")
class R09NoPoolAccount:
    id = "R09_no_pool_account"
    check_key = "R09_no_pool_account"
    clause_paths = ["DL2025/p9/ii"]
    consumes = ["repayment_debited_account_type", "pass_through_account_used_flag"]
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
            pass_through = facts.flag_of("pass_through_account_used_flag")
        except MissingFact:
            return NOT_APPLICABLE
        cite = [
            Citation(
                clause_path="DL2025/p9/ii",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("DL2025/p9/ii", ""),
            )
        ]
        if pass_through:
            return RuleOutcome(
                verdict="violation",
                citations=cite,
                rationale="Repayments flow through a lending-service-provider pass-through account.",
                inputs_used={"pass_through_account_used_flag": "true"},
            )
        return RuleOutcome(
            verdict="compliant",
            citations=cite,
            rationale="No pass-through account is used for repayment collection.",
            inputs_used={"pass_through_account_used_flag": "false"},
        )
