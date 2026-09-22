"""R19 — Recovery agent certified, with the transition allowance for existing agents
(RBC-AMD2026/p100F)."""

from datetime import date

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation
from app.rules.base import NOT_APPLICABLE, FactIndex, MissingFact, NotApplicable, RuleOutcome
from app.rules.registry import register

AMENDMENT_EFFECTIVE = date(2027, 1, 1)


@register(severity="major")
class R19AgentCertified:
    id = "R19_agent_certified"
    check_key = "R19_agent_certified"
    clause_paths = ["RBC-AMD2026/p100F"]
    consumes = ["agent_iibf_certified_flag"]
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
            certified = facts.flag_of("agent_iibf_certified_flag")
        except MissingFact:
            return NOT_APPLICABLE
        cite = [
            Citation(
                clause_path="RBC-AMD2026/p100F",
                role="decisive",
                quoted_clause_excerpt=clause_excerpts.get("RBC-AMD2026/p100F", ""),
            )
        ]
        if certified:
            return RuleOutcome(
                verdict="compliant",
                citations=cite,
                rationale="Recovery agent holds the required certification.",
                inputs_used={"agent_iibf_certified_flag": "true"},
            )
        return RuleOutcome(
            verdict="violation",
            citations=cite,
            rationale="Recovery agent does not hold the required certification.",
            inputs_used={"agent_iibf_certified_flag": "false"},
        )
