"""R17 — Microfinance contact-hour restriction (RBC2025/p45, resolved from the LLD's
non-canonical 'RBC2025 section H' basis per ADR-015).

This is the rule that decides the FIRST half of the PRD §11 temporal pair for a microfinance
borrower: before 2027-01-01, this rule is what governs contact hours (not R16, which gates on
the amendment's own commencement). For a NON-microfinance borrower this rule returns
NOT_APPLICABLE and Stage C correctly finds no governing provision before 2027.
"""

from datetime import date, time
from zoneinfo import ZoneInfo

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, NotApplicable, RuleOutcome
from app.rules.registry import register

WINDOW_OPEN = time(8, 0)
WINDOW_CLOSE = time(19, 0)
_IST = ZoneInfo("Asia/Kolkata")


@register(severity="major")
class R17MicrofinanceContactHours:
    id = "R17_microfinance_contact_hours"
    check_key = "R17_microfinance_contact_hours"
    clause_paths = ["RBC2025/p45"]
    consumes = ["contact_datetime"]
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
        if as_of < self.valid_from or not account.is_microfinance:
            return NOT_APPLICABLE

        ts = facts.datetime_of("contact_datetime")
        t = ts.astimezone(_IST).time()
        cite = [
            Citation(
                clause_path="RBC2025/p45",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("RBC2025/p45", ""),
            )
        ]
        inside = WINDOW_OPEN <= t <= WINDOW_CLOSE
        return RuleOutcome(
            verdict="compliant" if inside else "violation",
            citations=cite,
            rationale=(
                f"Microfinance borrower contacted at {t.strftime('%H:%M')} IST on "
                f"{ts.date().isoformat()}, "
                f"{'within' if inside else 'outside'} the permitted "
                f"{WINDOW_OPEN.strftime('%H:%M')}–{WINDOW_CLOSE.strftime('%H:%M')} window."
            ),
            inputs_used={"contact_datetime": ts.isoformat()},
        )
