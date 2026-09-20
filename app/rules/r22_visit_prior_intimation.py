"""R22 — At least one day's prior intimation before the first visit (RBC-AMD2026/p100I)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, MissingFact, NotApplicable, RuleOutcome
from app.rules.registry import register

AMENDMENT_EFFECTIVE = date(2027, 1, 1)
MIN_INTIMATION_DAYS = 1


@register(severity="major")
class R22VisitPriorIntimation:
    id = "R22_visit_prior_intimation"
    check_key = "R22_visit_prior_intimation"
    clause_paths = ["RBC-AMD2026/p100I"]
    consumes = ["visit_prior_intimation_date", "first_visit_date"]
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
        try:
            visit_date = facts.date_of("first_visit_date")
        except MissingFact:
            return NOT_APPLICABLE
        cite = [
            Citation(
                clause_path="RBC-AMD2026/p100I",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("RBC-AMD2026/p100I", ""),
            )
        ]
        try:
            intimation_date = facts.date_of("visit_prior_intimation_date")
        except MissingFact:
            return RuleOutcome(
                verdict="violation",
                citations=cite,
                rationale="A recovery visit occurred with no prior intimation on record.",
                inputs_used={"first_visit_date": visit_date.isoformat()},
            )
        lead_days = (visit_date - intimation_date).days
        if lead_days >= MIN_INTIMATION_DAYS:
            return RuleOutcome(
                verdict="compliant",
                citations=cite,
                rationale=f"Prior intimation given {lead_days} day(s) before the visit, meeting the {MIN_INTIMATION_DAYS}-day minimum.",
                inputs_used={"lead_days": str(lead_days)},
            )
        return RuleOutcome(
            verdict="violation",
            citations=cite,
            rationale=f"Prior intimation given only {lead_days} day(s) before the visit, below the {MIN_INTIMATION_DAYS}-day minimum.",
            inputs_used={"lead_days": str(lead_days)},
        )
