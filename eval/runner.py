"""Runs one eval case end to end against the real stack. LLD §17.4.

Cases with `stage: "verdict"` skip extraction — `expected.facts` is already the normalised
ground truth, not raw document text, so this module parses it directly into `FactValue`
rather than going through `app.extract`'s raw-text normalisers (which exist to handle messy
extracted strings, not clean ISO values a case author wrote by hand).

"Every case runs in a per-run tenant that is deleted afterwards" (LLD §17.4) — `run_case`
creates and tears down its own tenant/loan_account/document so evaluation never touches real
tenant data.
"""

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.config import Settings
from app.domain.documents import LoanAccountRef
from app.domain.facts import (
    BoolValue,
    DateTimeValue,
    DateValue,
    DaysValue,
    EnumValue,
    ExtractedFactOut,
    FactValue,
    IntValue,
    MoneyValue,
    RateValue,
    StringValue,
    value_to_jsonable,
)
from app.extract.service import extract_document
from app.llm.client import LLMClient
from app.schema.registry import FieldRegistry
from app.verdict.assess import assess_fact
from app.verdict.validator import is_literal_substring
from eval.loader import EvalCase

_DOC_TYPE_LIFECYCLE_STAGE_FALLBACK = "servicing"


def _parse_expected_value(value_type: str, raw: str) -> FactValue:
    if value_type == "date":
        return DateValue(v=date.fromisoformat(raw))
    if value_type == "datetime":
        return DateTimeValue(v=datetime.fromisoformat(raw))
    if value_type == "money":
        return MoneyValue(paise=int(raw))
    if value_type == "rate_bps":
        return RateValue(bps=int(raw))
    if value_type == "duration_days":
        return DaysValue(days=int(raw))
    if value_type == "integer":
        return IntValue(v=int(raw))
    if value_type == "boolean":
        return BoolValue(v=raw.strip().lower() in ("true", "yes", "1"))
    if value_type == "enum":
        return EnumValue(v=raw)
    return StringValue(v=raw)


@dataclass
class PersistedCitationCheck:
    clause_path: str
    role: str
    resolves_to_live_in_window_clause: bool
    is_hallucinated: bool


@dataclass
class FieldOutcome:
    field_key: str
    expected_present: bool
    actual_present: bool
    value_match: bool  # only meaningful when both expected_present and actual_present
    span_verified: bool


@dataclass
class ExtractionOutcome:
    case_ref: str
    fields: list[FieldOutcome] = field(default_factory=list)
    passed: bool = False
    diff: dict[str, Any] = field(default_factory=dict)


@dataclass
class CaseOutcome:
    case_ref: str
    verdict: str
    check_key: str
    decisive_citations: list[str] = field(default_factory=list)
    context_citations: list[str] = field(default_factory=list)
    all_citation_paths: list[str] = field(default_factory=list)
    persisted_citations: list[PersistedCitationCheck] = field(default_factory=list)
    passed: bool = False
    diff: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0


async def _resolve_citations(
    session: AsyncSession, assessment_ids: list[UUID], *, as_of: date
) -> list[PersistedCitationCheck]:
    """Independently re-derives `hallucinated_citation_rate` (LLD §17.2) from the database
    rather than trusting that `assess.py`/`validator.py` did their job — the whole point of
    an eval harness is to verify that, not assume it. A citation is hallucinated if its path
    is absent from the snapshot (the LEFT JOIN to `clause` produces NULLs) or its excerpt is
    not a literal substring of the clause's own text; separately, "resolves to a live,
    in-window clause" also requires the clause to actually be in force on `as_of`."""
    if not assessment_ids:
        return []
    rows = await session.execute(
        text("""
            SELECT ac.clause_path, ac.role, ac.quoted_clause_excerpt, c.text AS clause_text,
                   c.effective_from, c.effective_to
            FROM assessment_citation ac
            LEFT JOIN clause c ON c.id = ac.clause_id
            WHERE ac.assessment_id = ANY(:ids)
            """),
        {"ids": [str(i) for i in assessment_ids]},
    )
    out = []
    for row in rows:
        missing = row.clause_text is None
        excerpt_ok = (not missing) and is_literal_substring(
            row.quoted_clause_excerpt, row.clause_text
        )
        in_window = (
            (not missing)
            and (row.effective_from is None or row.effective_from <= as_of)
            and (row.effective_to is None or row.effective_to > as_of)
        )
        out.append(
            PersistedCitationCheck(
                clause_path=row.clause_path,
                role=row.role,
                resolves_to_live_in_window_clause=in_window,
                is_hallucinated=missing or not excerpt_ok,
            )
        )
    return out


async def run_case(
    session: AsyncSession,
    case: EvalCase,
    *,
    snapshot_id: UUID,
    settings: Settings,
    registry: FieldRegistry,
    client: LLMClient,
) -> CaseOutcome:
    tenant_id, loan_id, doc_id = uuid7(), uuid7(), uuid7()
    event_date = date.fromisoformat(case.event_date)

    try:
        await session.execute(
            text("INSERT INTO tenant (id, name) VALUES (:id, :name)"),
            {"id": str(tenant_id), "name": f"eval-{case.case_ref}"},
        )
        await session.execute(
            text(
                "INSERT INTO loan_account (id, tenant_id, external_ref, product_type, "
                "is_microfinance, is_digital_lending, device_financed) VALUES "
                "(:id, :tid, :ref, :pt, :mfi, :dl, :dev)"
            ),
            {
                "id": str(loan_id),
                "tid": str(tenant_id),
                "ref": case.case_ref,
                "pt": case.account_profile.product_type,
                "mfi": case.account_profile.is_microfinance,
                "dl": case.account_profile.is_digital_lending,
                "dev": case.account_profile.device_financed,
            },
        )
        await session.execute(
            text(
                "INSERT INTO document (id, tenant_id, loan_account_id, doc_type, "
                "lifecycle_stage, event_date, content_sha256, source_uri, char_count, "
                "span_budget_chars) VALUES (:id, :tid, :lid, :dt, :stage, :ed, :sha, "
                "'eval://synthetic', 0, 0)"
            ),
            {
                "id": str(doc_id),
                "tid": str(tenant_id),
                "lid": str(loan_id),
                "dt": case.doc_type,
                "stage": _DOC_TYPE_LIFECYCLE_STAGE_FALLBACK,
                "ed": event_date,
                "sha": uuid7().hex + uuid7().hex,
            },
        )

        trigger_field_key: str | None = None
        for field_key, raw_value in case.expected.facts.items():
            spec = registry.get(field_key)
            typed_value = _parse_expected_value(spec.type, raw_value)
            await session.execute(
                text("""
                    INSERT INTO extracted_fact
                        (id, tenant_id, document_id, loan_account_id, field_key, value_type,
                         value_raw, value_normalized, is_absent, confidence, extraction_run_id)
                    VALUES
                        (:id, :tid, :did, :lid, :fk, :vt, :vraw, CAST(:vn AS jsonb), false,
                         1.0, :run)
                    """),
                {
                    "id": str(uuid7()),
                    "tid": str(tenant_id),
                    "did": str(doc_id),
                    "lid": str(loan_id),
                    "fk": field_key,
                    "vt": spec.type,
                    "vraw": raw_value,
                    "vn": json.dumps(value_to_jsonable(typed_value)),
                    "run": str(uuid7()),
                },
            )
            if case.expected.check_key == f"F:{field_key}" or trigger_field_key is None:
                trigger_field_key = field_key

        assert trigger_field_key is not None, f"{case.case_ref}: expected.facts is empty"
        spec = registry.get(trigger_field_key)
        typed_value = _parse_expected_value(spec.type, case.expected.facts[trigger_field_key])
        fact = ExtractedFactOut(
            id=uuid7(),
            document_id=doc_id,
            loan_account_id=loan_id,
            field_key=trigger_field_key,
            value=typed_value,
            value_raw=case.expected.facts[trigger_field_key],
            is_absent=False,
            confidence=1.0,
        )
        account = LoanAccountRef(
            id=loan_id,
            tenant_id=tenant_id,
            external_ref=case.case_ref,
            product_type=case.account_profile.product_type,
            is_microfinance=case.account_profile.is_microfinance,
            is_digital_lending=case.account_profile.is_digital_lending,
            device_financed=case.account_profile.device_financed,
        )

        results = await assess_fact(
            session=session,
            fact=fact,
            account=account,
            document_event_date=event_date,
            snapshot_id=snapshot_id,
            settings=settings,
            registry=registry,
            client=client,
            request_id=f"eval-{case.case_ref}",
        )
        await session.commit()

        matching = [r for r in results if r.check_key == case.expected.check_key]
        result = matching[0] if matching else (results[0] if results else None)

        if result is None:
            outcome = CaseOutcome(
                case_ref=case.case_ref,
                verdict="__no_result__",
                check_key="__none__",
                passed=False,
                diff={"error": "assess_fact returned no results at all"},
            )
        else:
            decisive = [c.clause_path for c in result.citations if c.role == "decisive"]
            context = [c.clause_path for c in result.citations if c.role == "context_only"]
            all_paths = [c.clause_path for c in result.citations]

            assessment_row = (
                await session.execute(
                    text(
                        "SELECT id FROM assessment WHERE loan_account_id = :lid "
                        "AND check_key = :ck ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"lid": str(loan_id), "ck": result.check_key},
                )
            ).first()
            persisted = await _resolve_citations(
                session, [assessment_row.id] if assessment_row else [], as_of=event_date
            )

            forbidden_hit = [p for p in all_paths if p in case.expected.forbidden_citations]
            diff: dict[str, Any] = {}
            if result.verdict != case.expected.verdict:
                diff["verdict"] = {"expected": case.expected.verdict, "actual": result.verdict}
            if set(decisive) != set(case.expected.decisive_citations):
                diff["decisive_citations"] = {
                    "expected": case.expected.decisive_citations,
                    "actual": decisive,
                }
            if set(context) != set(case.expected.context_citations):
                diff["context_citations"] = {
                    "expected": case.expected.context_citations,
                    "actual": context,
                }
            if forbidden_hit:
                diff["forbidden_citations_present"] = forbidden_hit

            outcome = CaseOutcome(
                case_ref=case.case_ref,
                verdict=result.verdict,
                check_key=result.check_key,
                decisive_citations=decisive,
                context_citations=context,
                all_citation_paths=all_paths,
                persisted_citations=persisted,
                passed=not diff,
                diff=diff,
            )

        return outcome
    finally:
        await session.execute(
            text(
                "DELETE FROM assessment_citation WHERE assessment_id IN "
                "(SELECT id FROM assessment WHERE loan_account_id = :lid)"
            ),
            {"lid": str(loan_id)},
        )
        await session.execute(
            text("DELETE FROM assessment WHERE loan_account_id = :lid"), {"lid": str(loan_id)}
        )
        await session.execute(
            text("DELETE FROM loan_compliance_state WHERE loan_account_id = :lid"),
            {"lid": str(loan_id)},
        )
        await session.execute(
            text("DELETE FROM extracted_fact WHERE loan_account_id = :lid"),
            {"lid": str(loan_id)},
        )
        await session.execute(text("DELETE FROM document WHERE id = :id"), {"id": str(doc_id)})
        await session.execute(text("DELETE FROM loan_account WHERE id = :id"), {"id": str(loan_id)})
        await session.execute(text("DELETE FROM tenant WHERE id = :id"), {"id": str(tenant_id)})
        await session.commit()


async def run_extraction_case(
    session: AsyncSession,
    case: EvalCase,
    *,
    settings: Settings,
    registry: FieldRegistry,
    client: LLMClient,
    fixtures_dir: str = "eval/fixtures",
) -> ExtractionOutcome:
    """Runs Stage A extraction (LLD §9) for real against a fixture's document text — no
    ground truth is injected pre-extraction, unlike `run_case`'s verdict-stage shortcut.
    `case.input_ref` names the fixture file (relative to `fixtures_dir`); `case.expected.facts`
    is the ground truth the generator itself used to render that fixture (see
    scripts/gen_synthetic_docs.py). A field registered for `case.doc_type` but absent from
    `expected.facts` is expected absent."""
    if not case.input_ref:
        raise ValueError(f"{case.case_ref}: extraction-stage case requires input_ref")
    document_text = (Path(fixtures_dir) / case.input_ref).read_text()

    tenant_id, loan_id, doc_id = uuid7(), uuid7(), uuid7()
    event_date = date.fromisoformat(case.event_date)

    try:
        await session.execute(
            text("INSERT INTO tenant (id, name) VALUES (:id, :name)"),
            {"id": str(tenant_id), "name": f"eval-{case.case_ref}"},
        )
        await session.execute(
            text(
                "INSERT INTO loan_account (id, tenant_id, external_ref, product_type, "
                "is_microfinance, is_digital_lending, device_financed) VALUES "
                "(:id, :tid, :ref, :pt, :mfi, :dl, :dev)"
            ),
            {
                "id": str(loan_id),
                "tid": str(tenant_id),
                "ref": case.case_ref,
                "pt": case.account_profile.product_type,
                "mfi": case.account_profile.is_microfinance,
                "dl": case.account_profile.is_digital_lending,
                "dev": case.account_profile.device_financed,
            },
        )
        await session.execute(
            text(
                "INSERT INTO document (id, tenant_id, loan_account_id, doc_type, "
                "lifecycle_stage, event_date, content_sha256, source_uri, char_count, "
                "span_budget_chars) VALUES (:id, :tid, :lid, :dt, :stage, :ed, :sha, "
                "'eval://synthetic', :cc, :budget)"
            ),
            {
                "id": str(doc_id),
                "tid": str(tenant_id),
                "lid": str(loan_id),
                "dt": case.doc_type,
                "stage": _DOC_TYPE_LIFECYCLE_STAGE_FALLBACK,
                "ed": event_date,
                "sha": uuid7().hex + uuid7().hex,
                "cc": len(document_text),
                "budget": max(1, int(len(document_text) * settings.span_budget_ratio)),
            },
        )

        await extract_document(
            session=session,
            document_id=doc_id,
            tenant_id=tenant_id,
            loan_account_id=loan_id,
            doc_type=case.doc_type,
            document_text=document_text,
            client=client,
            registry=registry,
            settings=settings,
        )
        await session.commit()

        rows = await session.execute(
            text(
                "SELECT field_key, is_absent, value_normalized, span_verified "
                "FROM extracted_fact WHERE document_id = :did"
            ),
            {"did": str(doc_id)},
        )
        by_field = {r.field_key: r for r in rows}

        field_outcomes: list[FieldOutcome] = []
        mismatches: dict[str, Any] = {}
        for spec in registry.for_doc_type(case.doc_type):
            expected_present = spec.key in case.expected.facts
            row = by_field.get(spec.key)
            actual_present = row is not None and not row.is_absent
            value_match = False
            span_verified = bool(row.span_verified) if row is not None else False

            if expected_present and actual_present:
                expected_typed = _parse_expected_value(spec.type, case.expected.facts[spec.key])
                expected_jsonable = value_to_jsonable(expected_typed)
                actual_jsonable = (
                    json.loads(row.value_normalized)
                    if isinstance(row.value_normalized, str)
                    else row.value_normalized
                )
                value_match = actual_jsonable == expected_jsonable
                if not value_match:
                    mismatches[spec.key] = {
                        "expected": expected_jsonable,
                        "actual": actual_jsonable,
                    }
            elif expected_present != actual_present:
                mismatches[spec.key] = {
                    "expected_present": expected_present,
                    "actual_present": actual_present,
                }

            field_outcomes.append(
                FieldOutcome(
                    field_key=spec.key,
                    expected_present=expected_present,
                    actual_present=actual_present,
                    value_match=value_match,
                    span_verified=span_verified,
                )
            )

        outcome = ExtractionOutcome(
            case_ref=case.case_ref,
            fields=field_outcomes,
            passed=not mismatches,
            diff=mismatches,
        )
        return outcome
    finally:
        await session.execute(
            text("DELETE FROM extracted_fact WHERE document_id = :did"), {"did": str(doc_id)}
        )
        await session.execute(text("DELETE FROM document WHERE id = :id"), {"id": str(doc_id)})
        await session.execute(text("DELETE FROM loan_account WHERE id = :id"), {"id": str(loan_id)})
        await session.execute(text("DELETE FROM tenant WHERE id = :id"), {"id": str(tenant_id)})
        await session.commit()
