"""R13 — Data processed abroad deleted from offshore servers within 24 hours (DL2025/p13)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, MissingFact, NotApplicable, RuleOutcome
from app.rules.registry import register

MAX_HOURS = 24


@register(severity="major")
class R13OffshoreDeletion:
    id = "R13_offshore_deletion"
    check_key = "R13_offshore_deletion"
    clause_paths = ["DL2025/p13"]
    consumes = ["data_stored_offshore_flag", "offshore_deletion_within_hours"]
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
        if not facts.flag_of("data_stored_offshore_flag", default=False):
            return NOT_APPLICABLE
        cite = [
            Citation(
                clause_path="DL2025/p13",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("DL2025/p13", ""),
            )
        ]
        try:
            hours = facts.int_of("offshore_deletion_within_hours")
        except MissingFact:
            return RuleOutcome(
                verdict="violation",
                citations=cite,
                rationale="Data is processed offshore but no deletion window is disclosed.",
                inputs_used={"data_stored_offshore_flag": "true"},
            )
        if hours <= MAX_HOURS:
            return RuleOutcome(
                verdict="compliant",
                citations=cite,
                rationale=f"Offshore-processed data is deleted within {hours} hour(s), within the {MAX_HOURS}-hour requirement.",
                inputs_used={"offshore_deletion_within_hours": str(hours)},
            )
        return RuleOutcome(
            verdict="violation",
            citations=cite,
            rationale=f"Offshore-processed data is deleted within {hours} hour(s), exceeding the {MAX_HOURS}-hour requirement.",
            inputs_used={"offshore_deletion_within_hours": str(hours)},
        )
