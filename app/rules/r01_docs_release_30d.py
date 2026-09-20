"""LLD §11.3, in full — the release-timeline rule."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, NotApplicable, RuleOutcome
from app.rules.registry import register

RELEASE_WINDOW_DAYS = 30


@register(severity="critical")
class R01DocsRelease30d:
    id = "R01_docs_release_30d"
    check_key = "R01_docs_release_30d"
    clause_paths = ["RBC2025/p35"]
    consumes = ["full_repayment_date", "original_docs_released_date", "docs_lost_flag"]
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
        if as_of < self.valid_from:
            return NOT_APPLICABLE
        if facts.flag_of("docs_lost_flag", default=False):
            return NOT_APPLICABLE  # R02b handles the lost-documents limb

        repaid = facts.date_of("full_repayment_date")
        released = facts.date_of("original_docs_released_date")
        delay = (released - repaid).days
        cite = [
            Citation(
                clause_path="RBC2025/p35",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("RBC2025/p35", ""),
            )
        ]
        if delay <= RELEASE_WINDOW_DAYS:
            return RuleOutcome(
                verdict="compliant",
                citations=cite,
                rationale=(
                    f"Documents released {delay} day(s) after full repayment on "
                    f"{repaid.isoformat()}, within the {RELEASE_WINDOW_DAYS}-day window."
                ),
                inputs_used={
                    "full_repayment_date": repaid.isoformat(),
                    "original_docs_released_date": released.isoformat(),
                },
            )
        return RuleOutcome(
            verdict="violation",
            citations=cite,
            rationale=(
                f"Documents released {delay} day(s) after full repayment on "
                f"{repaid.isoformat()}, exceeding the {RELEASE_WINDOW_DAYS}-day window by "
                f"{delay - RELEASE_WINDOW_DAYS} day(s)."
            ),
            inputs_used={
                "full_repayment_date": repaid.isoformat(),
                "original_docs_released_date": released.isoformat(),
                "delay_days": str(delay),
            },
        )
