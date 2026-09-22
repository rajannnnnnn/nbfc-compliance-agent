"""R27 — KFS reproduced as a summary box within the loan agreement (KFS2024/p2)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, NotApplicable, RuleOutcome
from app.rules.registry import register


@register(severity="minor")
class R27KfsSummaryReproduced:
    id = "R27_kfs_summary_reproduced"
    check_key = "R27_kfs_summary_reproduced"
    clause_paths = ["KFS2024/p2"]
    consumes = ["kfs_summary_in_agreement_flag"]
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
        if not facts.has("kfs_summary_in_agreement_flag"):
            return NOT_APPLICABLE
        reproduced = facts.flag_of("kfs_summary_in_agreement_flag")
        cite = [
            Citation(
                clause_path="KFS2024/p2",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("KFS2024/p2", ""),
            )
        ]
        if reproduced:
            return RuleOutcome(
                verdict="compliant",
                citations=cite,
                rationale="KFS particulars are reproduced as a summary box in the loan agreement.",
                inputs_used={"kfs_summary_in_agreement_flag": "true"},
            )
        return RuleOutcome(
            verdict="violation",
            citations=cite,
            rationale="KFS particulars are not reproduced as a summary box in the loan agreement.",
            inputs_used={"kfs_summary_in_agreement_flag": "false"},
        )
