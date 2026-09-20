"""R21 — No disclosure about the borrower on social media (RBC-AMD2026/p100X)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, NotApplicable, RuleOutcome
from app.rules.registry import register

AMENDMENT_EFFECTIVE = date(2027, 1, 1)


@register(severity="major")
class R21NoSocialMediaDisclosure:
    id = "R21_no_social_media_disclosure"
    check_key = "R21_no_social_media_disclosure"
    clause_paths = ["RBC-AMD2026/p100X"]
    consumes = ["social_media_disclosure_flag"]
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
        disclosed = facts.flag_of("social_media_disclosure_flag", default=False)
        cite = [
            Citation(
                clause_path="RBC-AMD2026/p100X",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("RBC-AMD2026/p100X", ""),
            )
        ]
        if disclosed:
            return RuleOutcome(
                verdict="violation",
                citations=cite,
                rationale="Borrower's account status was disclosed on a social media platform.",
                inputs_used={"social_media_disclosure_flag": "true"},
            )
        return RuleOutcome(
            verdict="compliant",
            citations=cite,
            rationale="No social media disclosure about the borrower is on record.",
            inputs_used={"social_media_disclosure_flag": "false"},
        )
