"""R18 — Call recording preserved six months from the call date (RBC-AMD2026/p100N)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, MissingFact, NotApplicable, RuleOutcome
from app.rules.registry import register

MIN_RETENTION_DAYS = 180
AMENDMENT_EFFECTIVE = date(2027, 1, 1)


@register(severity="minor")
class R18RecordingRetention:
    id = "R18_recording_retention"
    check_key = "R18_recording_retention"
    clause_paths = ["RBC-AMD2026/p100N"]
    consumes = ["call_recorded_flag", "recording_retention_days"]
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
        if not facts.flag_of("call_recorded_flag", default=False):
            return NOT_APPLICABLE
        cite = [
            Citation(
                clause_path="RBC-AMD2026/p100N",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("RBC-AMD2026/p100N", ""),
            )
        ]
        try:
            retention_days = facts.int_of("recording_retention_days")
        except MissingFact:
            return RuleOutcome(
                verdict="violation",
                citations=cite,
                rationale="Call is recorded but no retention period is disclosed.",
                inputs_used={"call_recorded_flag": "true"},
            )
        if retention_days >= MIN_RETENTION_DAYS:
            return RuleOutcome(
                verdict="compliant",
                citations=cite,
                rationale=f"Recording retention of {retention_days} day(s) meets the six-month minimum.",
                inputs_used={"recording_retention_days": str(retention_days)},
            )
        return RuleOutcome(
            verdict="violation",
            citations=cite,
            rationale=f"Recording retention of {retention_days} day(s) is below the six-month minimum.",
            inputs_used={"recording_retention_days": str(retention_days)},
        )
