"""R02b — Lost-document limb: duplicates assisted, plus 30 days over and above (RBC2025 §F,
resolved to RBC2025/p40 per ADR-015)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, NotApplicable, RuleOutcome
from app.rules.registry import register

EXTRA_WINDOW_DAYS = 30


@register(severity="critical")
class R02bLostDocuments:
    id = "R02b_lost_documents"
    check_key = "R02b_lost_documents"
    clause_paths = ["RBC2025/p40"]
    consumes = [
        "docs_lost_flag",
        "duplicate_docs_assistance_offered_flag",
        "full_repayment_date",
        "original_docs_released_date",
    ]
    valid_from = date(2025, 11, 28)
    valid_to = None

    def evaluate(
        self,
        facts: FactIndex,
        account: LoanAccountRef,
        *,
        as_of: date,
        clause_excerpts: dict[str, str],
    ) -> RuleOutcome | NotApplicable:
        if as_of < self.valid_from or not facts.flag_of("docs_lost_flag", default=False):
            return NOT_APPLICABLE

        assisted = facts.flag_of("duplicate_docs_assistance_offered_flag", default=False)
        repaid = facts.date_of("full_repayment_date")
        released = facts.date_of("original_docs_released_date")
        delay = (released - repaid).days
        extended_window = 30 + EXTRA_WINDOW_DAYS
        cite = [
            Citation(
                clause_path="RBC2025/p40",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("RBC2025/p40", ""),
            )
        ]

        if not assisted:
            return RuleOutcome(
                verdict="violation",
                citations=cite,
                rationale="Original documents reported lost, but no assistance with duplicates is on record.",
                inputs_used={
                    "docs_lost_flag": "true",
                    "duplicate_docs_assistance_offered_flag": "false",
                },
            )
        if delay <= extended_window:
            return RuleOutcome(
                verdict="compliant",
                citations=cite,
                rationale=f"Documents lost; duplicates assisted and released within the extended {extended_window}-day window ({delay} days).",
                inputs_used={"delay_days": str(delay)},
            )
        return RuleOutcome(
            verdict="violation",
            citations=cite,
            rationale=f"Documents lost; released {delay} days after repayment, exceeding the extended {extended_window}-day window.",
            inputs_used={"delay_days": str(delay)},
        )
