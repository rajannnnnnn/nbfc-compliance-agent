"""R26 — KFS carried a unique proposal number valid at least three working days (KFS2024/p1)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, MissingFact, NotApplicable, RuleOutcome
from app.rules.registry import register

MIN_VALIDITY_DAYS = 3


@register(severity="minor")
class R26KfsValidity:
    id = "R26_kfs_validity"
    check_key = "R26_kfs_validity"
    clause_paths = ["KFS2024/p1"]
    consumes = ["loan_proposal_number", "kfs_validity_days"]
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
        if not facts.has("loan_proposal_number") and not facts.has("kfs_validity_days"):
            return NOT_APPLICABLE
        cite = [
            Citation(
                clause_path="KFS2024/p1",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("KFS2024/p1", ""),
            )
        ]

        if not facts.has("loan_proposal_number"):
            return RuleOutcome(
                verdict="violation",
                citations=cite,
                rationale="No unique proposal number is disclosed on the KFS.",
                inputs_used={},
            )
        try:
            validity_days = facts.int_of("kfs_validity_days")
        except MissingFact:
            return RuleOutcome(
                verdict="violation",
                citations=cite,
                rationale="KFS validity period is not disclosed.",
                inputs_used={"loan_proposal_number": "present"},
            )
        if validity_days >= MIN_VALIDITY_DAYS:
            return RuleOutcome(
                verdict="compliant",
                citations=cite,
                rationale=f"KFS carries a unique proposal number and a validity of {validity_days} day(s), meeting the {MIN_VALIDITY_DAYS}-day minimum.",
                inputs_used={"kfs_validity_days": str(validity_days)},
            )
        return RuleOutcome(
            verdict="violation",
            citations=cite,
            rationale=f"KFS validity of {validity_days} day(s) is below the {MIN_VALIDITY_DAYS}-day minimum.",
            inputs_used={"kfs_validity_days": str(validity_days)},
        )
