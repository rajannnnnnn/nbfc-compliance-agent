"""R03 — APR identical across KFS, agreement and sanction letter.

This rule compares the SAME field (apr_bps) across THREE different document types, but
FactIndex exposes only the latest fact per field key across the whole account (LLD §11.1) —
it cannot see "the KFS's apr_bps" versus "the agreement's apr_bps" as distinct values. The
actual three-way comparison is conflicts/detector.py's "apr" group (conflicts.yaml, M7),
which reads the raw per-document fact rows directly and raises this check_key on a mismatch.
This class exists so the rule registers (boot pinning validation, severity mapping,
check_key addressability) with the correct id and clause basis; assess.py never calls its
evaluate() for this rule — conflicts/detector.py constructs the RuleOutcome itself from the
comparison it already had to do to detect the conflict in the first place.
"""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.rules.base import NOT_APPLICABLE, FactIndex, NotApplicable, RuleOutcome
from app.rules.registry import register


@register(severity="critical")
class R03AprConsistency:
    id = "R03_apr_consistency"
    check_key = "R03_apr_consistency"
    clause_paths = ["KFS2024/annexA/part1/9"]
    consumes = ["apr_bps"]
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
        return NOT_APPLICABLE  # see module docstring — conflicts/detector.py decides this check
