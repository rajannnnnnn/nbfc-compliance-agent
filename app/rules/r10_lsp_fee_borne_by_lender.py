"""R10 — Lending-service-provider fees borne by the lender, not the borrower (DL2025/p9/iii)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, MissingFact, NotApplicable, RuleOutcome
from app.rules.registry import register


@register(severity="major")
class R10LspFeeBorneByLender:
    id = "R10_lsp_fee_borne_by_lender"
    check_key = "R10_lsp_fee_borne_by_lender"
    clause_paths = ["DL2025/p9/iii"]
    consumes = ["lsp_fee_borne_by"]
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
            borne_by = facts.string_of("lsp_fee_borne_by")
        except MissingFact:
            return NOT_APPLICABLE
        cite = [
            Citation(
                clause_path="DL2025/p9/iii",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("DL2025/p9/iii", ""),
            )
        ]
        if borne_by == "lender":
            return RuleOutcome(
                verdict="compliant",
                citations=cite,
                rationale="The lending service provider's fee is borne by the regulated entity.",
                inputs_used={"lsp_fee_borne_by": borne_by},
            )
        return RuleOutcome(
            verdict="violation",
            citations=cite,
            rationale=f"The lending service provider's fee is borne by {borne_by}, not the regulated entity.",
            inputs_used={"lsp_fee_borne_by": borne_by},
        )
