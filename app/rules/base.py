"""Rule protocol, RuleOutcome, NotApplicable, registry. LLD §11.1.

Rules are pure and synchronous. No session, no network, no clock — `as_of` is passed in, and
a rule that calls `date.today()` is a defect (tested by an AST walk, LLD §19).

Per ADR-007: `evaluate` takes a fourth parameter, `clause_excerpts`, a pre-resolved
clause_path -> text map loaded once per assessment by verdict/assess.py — LLD §11.1's
`facts.clause_excerpt(path)` would require the FactIndex to reach the database, which
contradicts "no session, no network" two sentences later in the same spec section.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from app.domain.documents import LoanAccountRef
from app.domain.verdicts import Citation


class NotApplicable:
    pass


NOT_APPLICABLE = NotApplicable()


class MissingFact(Exception):
    pass


class RuleOutcome(BaseModel):
    verdict: Literal["compliant", "violation", "ambiguous"]
    citations: list[Citation]
    rationale: str
    inputs_used: dict[str, str]


@dataclass
class FactRecord:
    field_key: str
    value_type: str | None
    value_normalized: dict[str, Any] | None
    is_absent: bool


@dataclass
class FactIndex:
    """Read-only mapping from field key to the latest fact for that key on the account."""

    facts: dict[str, FactRecord] = field(default_factory=dict)

    def _get(self, field_key: str) -> FactRecord:
        record = self.facts.get(field_key)
        if record is None or record.is_absent:
            raise MissingFact(field_key)
        return record

    @staticmethod
    def _value(record: FactRecord) -> dict[str, Any]:
        # is_absent False guarantees value_normalized is not None (the extraction pipeline's
        # own invariant, mirrored by the DB CHECK constraint) — asserted here for mypy and as
        # a runtime guard against that invariant ever being violated.
        assert (
            record.value_normalized is not None
        ), f"{record.field_key}: present fact with no value"
        return record.value_normalized

    def flag_of(self, field_key: str, *, default: bool | None = None) -> bool:
        try:
            record = self._get(field_key)
        except MissingFact:
            if default is not None:
                return default
            raise
        return bool(self._value(record)["v"])

    def date_of(self, field_key: str) -> date:
        record = self._get(field_key)
        return date.fromisoformat(self._value(record)["v"])

    def money_of(self, field_key: str) -> int:
        record = self._get(field_key)
        return int(self._value(record)["paise"])

    def bps_of(self, field_key: str) -> int:
        record = self._get(field_key)
        return int(self._value(record)["bps"])

    def datetime_of(self, field_key: str) -> datetime:
        record = self._get(field_key)
        return datetime.fromisoformat(self._value(record)["v"])

    def int_of(self, field_key: str) -> int:
        record = self._get(field_key)
        v = self._value(record)
        return int(v["v"] if "v" in v else v["days"])

    def string_of(self, field_key: str) -> str:
        record = self._get(field_key)
        return str(self._value(record)["v"])

    def has(self, field_key: str) -> bool:
        record = self.facts.get(field_key)
        return record is not None and not record.is_absent


class Rule(Protocol):
    id: str
    check_key: str
    clause_paths: list[str]
    consumes: list[str]
    valid_from: date | None
    valid_to: date | None

    def evaluate(
        self,
        facts: FactIndex,
        account: LoanAccountRef,
        *,
        as_of: date,
        clause_excerpts: dict[str, str],
    ) -> RuleOutcome | NotApplicable: ...
