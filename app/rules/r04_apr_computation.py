"""R04 — APR consistent with rate, fees and tenor on the circular's own basis.

Best-effort reducing-balance approximation: effective APR should not exceed the nominal
interest rate by more than a tolerance once the disclosed fee load is annualised over the
loan term. This is a simplified proxy, not the regulator's own prescribed computation
methodology, which is not in the placeholder corpus (KFS2024/annexB is named but not
structurally specified anywhere in the document set — see docs/SPEC_QUERIES.md SQ-06).
"""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, MissingFact, NotApplicable, RuleOutcome
from app.rules.registry import register

TOLERANCE_BPS = 200  # 2 percentage points


@register(severity="major")
class R04AprComputation:
    id = "R04_apr_computation"
    check_key = "R04_apr_computation"
    clause_paths = ["KFS2024/annexA/part1/9"]
    consumes = ["apr_bps", "interest_rate_bps", "fees_total", "sanctioned_amount", "loan_term_days"]
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
        try:
            apr = facts.bps_of("apr_bps")
            rate = facts.bps_of("interest_rate_bps")
            fees = facts.money_of("fees_total")
            principal = facts.money_of("sanctioned_amount")
            term_days = facts.int_of("loan_term_days")
        except MissingFact:
            return NOT_APPLICABLE

        if principal <= 0 or term_days <= 0:
            return NOT_APPLICABLE

        term_years = term_days / 365
        fee_load_bps = round((fees / principal) * 10000 / term_years) if term_years > 0 else 0
        implied_apr = rate + fee_load_bps
        diff = abs(apr - implied_apr)

        cite = [
            Citation(
                clause_path="KFS2024/annexA/part1/9",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("KFS2024/annexA/part1/9", ""),
            )
        ]
        if diff <= TOLERANCE_BPS:
            return RuleOutcome(
                verdict="compliant",
                citations=cite,
                rationale=f"Disclosed APR ({apr} bps) is within {TOLERANCE_BPS} bps of the rate-plus-fees estimate ({implied_apr} bps).",
                inputs_used={"apr_bps": str(apr), "implied_apr_bps": str(implied_apr)},
            )
        return RuleOutcome(
            verdict="ambiguous",
            citations=cite,
            rationale=f"Disclosed APR ({apr} bps) differs from the rate-plus-fees estimate ({implied_apr} bps) by {diff} bps, beyond the {TOLERANCE_BPS} bps tolerance of this approximate check.",
            inputs_used={
                "apr_bps": str(apr),
                "implied_apr_bps": str(implied_apr),
                "diff_bps": str(diff),
            },
        )
