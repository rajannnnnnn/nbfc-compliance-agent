"""Cross-document conflict detection. LLD §12 / M7-T02.

A conflict is not a verdict — it raises a check, scoped to `group.raises_check`, never a full
account re-run (that scoping is what keeps this a rule rather than a planner, per CLAUDE.md
§5). `detect_for_fact` returns the list of persisted conflicts and, separately, the set of
`(loan_account_id, check_key)` pairs the caller must re-assess — actually enqueuing that
re-assessment (via Celery, per LLD §14) is M8's job; nothing here imports a queue client.
"""

import json
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.conflicts.loader import ConflictGroup, ConflictMember, ConflictRegistry
from app.domain.enums import ConflictType
from app.domain.facts import (
    DaysValue,
    ExtractedFactOut,
    FactValue,
    MoneyValue,
    RateValue,
)
from app.obs.metrics import conflicts_detected_total

_FACT_VALUE_ADAPTER: TypeAdapter[FactValue] = TypeAdapter(FactValue)

_LATEST_FACT_FOR_MEMBER_SQL = """
SELECT ef.id, ef.value_normalized
FROM extracted_fact ef
JOIN document d ON d.id = ef.document_id
WHERE ef.loan_account_id = :loan_account_id
  AND ef.field_key = :field_key
  AND d.doc_type = :doc_type
  AND ef.is_absent = false
ORDER BY ef.created_at DESC
LIMIT 1
"""


class ConflictComparisonError(Exception):
    """A group compares two FactValues of different `kind` — a conflicts.yaml authoring
    defect (the two members should never disagree on value type), not a data problem."""


@dataclass
class FetchedFact:
    id: UUID
    value: FactValue


@dataclass
class DetectedConflict:
    group_key: str
    field_key: str
    fact_a_id: UUID
    fact_b_id: UUID
    conflict_type: str
    operator: str
    delta: dict[str, Any]
    raises_check: str


def _scalar_of(value: FactValue) -> Any:
    if isinstance(value, MoneyValue):
        return value.paise
    if isinstance(value, RateValue):
        return value.bps
    if isinstance(value, DaysValue):
        return value.days
    return value.v


def _require_same_kind(a: FactValue, b: FactValue) -> None:
    if a.kind != b.kind:
        raise ConflictComparisonError(
            f"cannot compare {a.kind!r} against {b.kind!r} — a conflicts.yaml group must pair "
            "fields of the same value type"
        )


def compare(op: str, a: FactValue, b: FactValue, params: dict[str, Any]) -> bool:
    """Returns True when `a` and `b` are consistent (no conflict). Compares normalised values
    only, never `value_raw` — CLAUDE.md's "facts never carry judgements" extends to conflict
    detection: this compares typed data, never document prose."""
    _require_same_kind(a, b)
    av, bv = _scalar_of(a), _scalar_of(b)

    if op == "equal":
        return bool(av == bv)

    if op == "equal_within":
        tolerance = params.get("tolerance", 0)
        if a.kind not in ("money", "rate_bps", "duration_days", "integer"):
            raise ConflictComparisonError(f"equal_within requires a numeric kind, got {a.kind!r}")
        return bool(abs(av - bv) <= tolerance)

    if op == "date_order":
        if not isinstance(av, date) or not isinstance(bv, date):
            raise ConflictComparisonError(
                f"date_order requires a date/datetime kind, got {a.kind!r}"
            )
        direction = params.get("direction")
        if direction == "after":
            within_days = params.get("within_days")
            if bv <= av:
                return False
            if within_days is not None:
                return bool((bv - av).days <= within_days)
            return True
        if direction == "before":
            return bool(bv < av)
        raise ConflictComparisonError(
            f"date_order direction {direction!r} needs a chain, not a pair"
        )

    raise ConflictComparisonError(f"unknown operator {op!r}")


def _delta_for(op: str, a: FactValue, b: FactValue) -> dict[str, Any]:
    av, bv = _scalar_of(a), _scalar_of(b)
    if isinstance(av, date):
        return {"a": av.isoformat(), "b": bv.isoformat(), "days": (bv - av).days}
    if isinstance(av, int | float):
        return {"a": av, "b": bv, "diff": av - bv}
    return {"a": str(av), "b": str(bv)}


def _conflict_type_for(op: str) -> str:
    if op == "equal_within":
        return ConflictType.TOLERANCE_BREACH
    if op == "date_order":
        return ConflictType.DATE_ORDER
    return ConflictType.VALUE_MISMATCH


async def _fetch_member_fact(
    session: AsyncSession, *, loan_account_id: UUID, member: ConflictMember
) -> FetchedFact | None:
    row = (
        await session.execute(
            text(_LATEST_FACT_FOR_MEMBER_SQL),
            {
                "loan_account_id": str(loan_account_id),
                "field_key": member.field,
                "doc_type": member.doc_type,
            },
        )
    ).first()
    if row is None or row.value_normalized is None:
        return None
    raw = row.value_normalized
    data = json.loads(raw) if isinstance(raw, str) else raw
    value = _FACT_VALUE_ADAPTER.validate_python(data)
    return FetchedFact(id=row.id, value=value)


def _member_of(
    fact: ExtractedFactOut, doc_type: str, group: ConflictGroup
) -> ConflictMember | None:
    for m in group.members:
        if m.field == fact.field_key and m.doc_type == doc_type:
            return m
    return None


async def _evaluate_pairwise_group(
    session: AsyncSession,
    *,
    loan_account_id: UUID,
    group: ConflictGroup,
    trigger_member: ConflictMember,
    trigger_fact: FetchedFact,
) -> list[DetectedConflict]:
    conflicts: list[DetectedConflict] = []
    params = dict(group.params)
    if group.tolerance is not None:
        params.setdefault("tolerance", group.tolerance)

    trigger_idx = group.members.index(trigger_member)

    for idx, other in enumerate(group.members):
        if other is trigger_member:
            continue
        counterpart = await _fetch_member_fact(
            session, loan_account_id=loan_account_id, member=other
        )
        if counterpart is None:
            continue

        # For date_order, "a"/"b" mean "earlier member"/"later member" per the group's own
        # listed order (LLD §12's own members list is the chronology), never "trigger fact"/
        # "counterpart fact" — those are which fact happened to just get extracted, which has
        # nothing to do with which one the group says should come first.
        if idx < trigger_idx:
            a_val, b_val, a_id, b_id = (
                counterpart.value,
                trigger_fact.value,
                counterpart.id,
                trigger_fact.id,
            )
        else:
            a_val, b_val, a_id, b_id = (
                trigger_fact.value,
                counterpart.value,
                trigger_fact.id,
                counterpart.id,
            )

        ok = compare(group.operator, a_val, b_val, params)
        if not ok:
            conflicts.append(
                DetectedConflict(
                    group_key=group.key,
                    field_key=trigger_member.field,
                    fact_a_id=a_id,
                    fact_b_id=b_id,
                    conflict_type=_conflict_type_for(group.operator),
                    operator=group.operator,
                    delta=_delta_for(group.operator, a_val, b_val),
                    raises_check=group.raises_check,
                )
            )
    return conflicts


async def _evaluate_strictly_increasing_group(
    session: AsyncSession, *, loan_account_id: UUID, group: ConflictGroup
) -> list[DetectedConflict]:
    fetched: list[FetchedFact | None] = [
        await _fetch_member_fact(session, loan_account_id=loan_account_id, member=m)
        for m in group.members
    ]
    conflicts: list[DetectedConflict] = []
    present = [(i, f) for i, f in enumerate(fetched) if f is not None]
    for (_i_a, fa), (i_b, fb) in zip(present, present[1:], strict=False):
        _require_same_kind(fa.value, fb.value)
        av, bv = _scalar_of(fa.value), _scalar_of(fb.value)
        if not isinstance(av, date) or not isinstance(bv, date):
            raise ConflictComparisonError("strictly_increasing requires a date/datetime kind")
        if not bv > av:
            conflicts.append(
                DetectedConflict(
                    group_key=group.key,
                    field_key=group.members[i_b].field,
                    fact_a_id=fa.id,
                    fact_b_id=fb.id,
                    conflict_type=ConflictType.DATE_ORDER,
                    operator=group.operator,
                    delta=_delta_for(group.operator, fa.value, fb.value),
                    raises_check=group.raises_check,
                )
            )
    return conflicts


async def detect_for_fact(
    *, session: AsyncSession, fact: ExtractedFactOut, doc_type: str, registry: ConflictRegistry
) -> list[DetectedConflict]:
    """Runs every conflict group that has a member matching `(doc_type, fact.field_key)`.
    Returns the detected conflicts; the caller persists them and enqueues
    `assess_check` for each conflict's `raises_check`, scoped to this loan account only."""
    if fact.is_absent or fact.value is None:
        return []

    groups = registry.groups_containing(doc_type=doc_type, field_key=fact.field_key)
    all_conflicts: list[DetectedConflict] = []

    for group in groups:
        direction = group.params.get("direction") if group.operator == "date_order" else None
        if direction == "strictly_increasing":
            all_conflicts.extend(
                await _evaluate_strictly_increasing_group(
                    session, loan_account_id=fact.loan_account_id, group=group
                )
            )
            continue

        trigger_member = _member_of(fact, doc_type, group)
        assert trigger_member is not None  # guaranteed by groups_containing
        trigger_fetched = FetchedFact(id=fact.id, value=fact.value)
        all_conflicts.extend(
            await _evaluate_pairwise_group(
                session,
                loan_account_id=fact.loan_account_id,
                group=group,
                trigger_member=trigger_member,
                trigger_fact=trigger_fetched,
            )
        )

    return all_conflicts


async def persist_conflicts(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    loan_account_id: UUID,
    conflicts: list[DetectedConflict],
) -> list[UUID]:
    ids: list[UUID] = []
    for c in conflicts:
        conflicts_detected_total.labels(group_key=c.group_key, conflict_type=c.conflict_type).inc()
        conflict_id = uuid7()
        await session.execute(
            text("""
                INSERT INTO fact_conflict
                    (id, tenant_id, loan_account_id, group_key, field_key, fact_a_id, fact_b_id,
                     conflict_type, delta, operator)
                VALUES
                    (:id, :tenant_id, :loan_account_id, :group_key, :field_key, :fact_a_id,
                     :fact_b_id, :conflict_type, CAST(:delta AS jsonb), :operator)
                ON CONFLICT (tenant_id, group_key, fact_a_id, fact_b_id) DO NOTHING
                """),
            {
                "id": str(conflict_id),
                "tenant_id": str(tenant_id),
                "loan_account_id": str(loan_account_id),
                "group_key": c.group_key,
                "field_key": c.field_key,
                "fact_a_id": str(c.fact_a_id),
                "fact_b_id": str(c.fact_b_id),
                "conflict_type": c.conflict_type,
                "delta": json.dumps(c.delta),
                "operator": c.operator,
            },
        )
        ids.append(conflict_id)
    return ids
