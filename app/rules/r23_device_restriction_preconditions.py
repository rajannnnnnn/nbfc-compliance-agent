"""R23 — Device restriction only where the loan financed the device, 60+ days past due, with
21-day then 7-day cure notices (RBC-AMD2026/p100Q-S)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, MissingFact, NotApplicable, RuleOutcome
from app.rules.registry import register

AMENDMENT_EFFECTIVE = date(2027, 1, 1)
MIN_DAYS_PAST_DUE = 60
CLAUSE_PATHS = ["RBC-AMD2026/p100Q", "RBC-AMD2026/p100R", "RBC-AMD2026/p100S"]


@register(severity="critical")
class R23DeviceRestrictionPreconditions:
    id = "R23_device_restriction_preconditions"
    check_key = "R23_device_restriction_preconditions"
    clause_paths = CLAUSE_PATHS
    consumes = [
        "device_restriction_applied_flag",
        "device_financed_by_loan_flag",
        "days_past_due_at_contact",
        "cure_notice_21day_sent_date",
        "cure_notice_7day_sent_date",
        "device_restriction_applied_date",
    ]
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
        if not facts.flag_of("device_restriction_applied_flag", default=False):
            return NOT_APPLICABLE

        cite = [
            Citation(
                clause_path=p, role="decisive", quoted_clause_excerpt=clause_excerpts.get(p, "")
            )
            for p in CLAUSE_PATHS
        ]

        failures = []
        if not facts.flag_of("device_financed_by_loan_flag", default=False):
            failures.append("the restricted device was not financed by this loan")

        try:
            days_past_due = facts.int_of("days_past_due_at_contact")
            if days_past_due < MIN_DAYS_PAST_DUE:
                failures.append(
                    f"only {days_past_due} day(s) past due, below the {MIN_DAYS_PAST_DUE}-day minimum"
                )
        except MissingFact:
            failures.append("days past due at restriction is not on record")

        notice21 = None
        notice7 = None
        try:
            notice21 = facts.date_of("cure_notice_21day_sent_date")
        except MissingFact:
            failures.append("no 21-day cure notice is on record")
        try:
            notice7 = facts.date_of("cure_notice_7day_sent_date")
        except MissingFact:
            failures.append("no 7-day cure notice is on record")
        if notice21 and notice7 and notice7 <= notice21:
            failures.append(
                "the 7-day cure notice was not sent strictly after the 21-day cure notice"
            )

        if failures:
            return RuleOutcome(
                verdict="violation",
                citations=cite,
                rationale="Device restriction preconditions not met: " + "; ".join(failures) + ".",
                inputs_used={"device_restriction_applied_flag": "true"},
            )
        return RuleOutcome(
            verdict="compliant",
            citations=cite,
            rationale="Device restriction preconditions (financed device, 60+ days past due, sequenced cure notices) are all met.",
            inputs_used={"days_past_due_at_contact": str(days_past_due)},
        )
