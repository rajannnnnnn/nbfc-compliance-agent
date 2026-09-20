"""LLD §11.3, in full — the contact-window rule.

Per ADR-014: reads the contact timestamp's wall time in Asia/Kolkata explicitly, not via
`.timetz()` on whatever tzinfo the datetime happens to carry (which silently shifts a 20:10
IST call to 14:40 if the value arrives UTC-tagged, flipping a violation to compliant). The
window is inclusive on both ends: 19:00:00 is the last permitted second.
"""

from datetime import date, time
from zoneinfo import ZoneInfo

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, NotApplicable, RuleOutcome
from app.rules.registry import register

WINDOW_OPEN = time(8, 0)
WINDOW_CLOSE = time(19, 0)
AMENDMENT_EFFECTIVE = date(2027, 1, 1)
_IST = ZoneInfo("Asia/Kolkata")


@register(severity="major")
class R16ContactWindow:
    id = "R16_contact_window"
    check_key = "R16_contact_window"
    clause_paths = ["RBC-AMD2026/p100W"]
    consumes = ["contact_datetime"]
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
            # Stage C retrieves nothing applicable and attaches this clause as context_only,
            # annotated with its commencement date — the mechanical implementation of the
            # PRD's defining behaviour.
            return NOT_APPLICABLE

        ts = facts.datetime_of("contact_datetime")
        t = ts.astimezone(_IST).time()
        cite = [
            Citation(
                clause_path="RBC-AMD2026/p100W",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("RBC-AMD2026/p100W", ""),
            )
        ]
        inside = WINDOW_OPEN <= t <= WINDOW_CLOSE
        return RuleOutcome(
            verdict="compliant" if inside else "violation",
            citations=cite,
            rationale=(
                f"Borrower contacted at {t.strftime('%H:%M')} IST on "
                f"{ts.date().isoformat()}, "
                f"{'within' if inside else 'outside'} the permitted "
                f"{WINDOW_OPEN.strftime('%H:%M')}–{WINDOW_CLOSE.strftime('%H:%M')} window."
            ),
            inputs_used={"contact_datetime": ts.isoformat()},
        )
