"""R02 — Rs 5,000/day compensation where release delay is attributable to the lender."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, MissingFact, NotApplicable, RuleOutcome
from app.rules.registry import register

RELEASE_WINDOW_DAYS = 30
COMPENSATION_PER_DAY_PAISE = 500_000  # Rs 5,000


@register(severity="critical")
class R02DocsReleaseCompensation:
    id = "R02_docs_release_compensation"
    check_key = "R02_docs_release_compensation"
    clause_paths = ["RBC2025/p39"]
    consumes = [
        "full_repayment_date",
        "original_docs_released_date",
        "release_delay_compensation_paid",
        "docs_lost_flag",
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
        if as_of < self.valid_from or facts.flag_of("docs_lost_flag", default=False):
            return NOT_APPLICABLE

        repaid = facts.date_of("full_repayment_date")
        released = facts.date_of("original_docs_released_date")
        delay = (released - repaid).days
        if delay <= RELEASE_WINDOW_DAYS:
            return NOT_APPLICABLE  # R01 compliant; no compensation obligation arises

        owed_days = delay - RELEASE_WINDOW_DAYS
        owed_paise = owed_days * COMPENSATION_PER_DAY_PAISE
        cite = [
            Citation(
                clause_path="RBC2025/p39",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("RBC2025/p39", ""),
            )
        ]

        try:
            paid_paise = facts.money_of("release_delay_compensation_paid")
        except MissingFact:
            return RuleOutcome(
                verdict="violation",
                citations=cite,
                rationale=f"Release delayed {owed_days} day(s) beyond the window; Rs {owed_paise // 100} owed but no compensation payment is on record.",
                inputs_used={"delay_days": str(delay), "owed_paise": str(owed_paise)},
            )

        if paid_paise >= owed_paise:
            return RuleOutcome(
                verdict="compliant",
                citations=cite,
                rationale=f"Compensation of Rs {paid_paise // 100} paid meets or exceeds the Rs {owed_paise // 100} owed for {owed_days} day(s) of delay.",
                inputs_used={"delay_days": str(delay), "paid_paise": str(paid_paise)},
            )
        return RuleOutcome(
            verdict="violation",
            citations=cite,
            rationale=f"Compensation of Rs {paid_paise // 100} paid is less than the Rs {owed_paise // 100} owed for {owed_days} day(s) of delay.",
            inputs_used={
                "delay_days": str(delay),
                "paid_paise": str(paid_paise),
                "owed_paise": str(owed_paise),
            },
        )
