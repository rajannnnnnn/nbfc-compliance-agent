"""Celery tasks for verdict assessment. LLD §14.

Task bodies are thin wrappers around an `async def _run_*` helper — all real logic lives
there so it is directly testable (via `asyncio.run` or `await` in an async test) without a
running Celery worker or broker. The tasks themselves are integration glue: parse the id-only
payload, open a session, call the helper, return a small result dict.

Per CLAUDE.md §2.3 / ADR-017: every task here takes ids only. Nothing here ever receives
document text — a fact's `value` and `quoted_span` already went through
`app.extract.service.extract_document` synchronously inside the API request handler before
this task was ever queued, so this module only ever reads back what extraction already wrote.
"""

import asyncio
import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.corpus.snapshot import get_active_snapshot_id
from app.db.engine import get_sessionmaker
from app.domain.documents import LoanAccountRef
from app.domain.facts import ExtractedFactOut, FactValue
from app.llm.client import LLMClient
from app.schema.registry import FieldRegistry
from app.tasks.celery_app import app
from app.verdict.assess import assess_fact

_ACCOUNT_REF_SQL = """
SELECT la.tenant_id, la.external_ref, la.product_type, la.is_microfinance,
       la.is_digital_lending, la.device_financed, t.entity_type
FROM loan_account la JOIN tenant t ON t.id = la.tenant_id
WHERE la.id = :loan_account_id
"""

_DOCUMENT_ROW_SQL = """
SELECT tenant_id, loan_account_id, event_date FROM document WHERE id = :document_id
"""

_FACTS_FOR_DOCUMENT_SQL = """
SELECT id, field_key, value_type, value_raw, value_normalized, is_absent, confidence
FROM extracted_fact WHERE document_id = :document_id AND is_absent = false
"""

_LATEST_FACT_FOR_FIELD_SQL = """
SELECT id, document_id, field_key, value_type, value_raw, value_normalized, is_absent, confidence
FROM extracted_fact
WHERE loan_account_id = :loan_account_id AND field_key = :field_key AND is_absent = false
ORDER BY created_at DESC LIMIT 1
"""

_ALL_ASSESSED_FIELD_KEYS_SQL = """
SELECT DISTINCT field_key FROM extracted_fact
WHERE loan_account_id = :loan_account_id AND is_absent = false
"""


class AssessmentTaskError(Exception):
    """A permanent failure — missing account/document/facts. Never auto-retried."""


async def _load_account_ref(session: AsyncSession, loan_account_id: UUID) -> LoanAccountRef:
    row = (
        await session.execute(text(_ACCOUNT_REF_SQL), {"loan_account_id": str(loan_account_id)})
    ).first()
    if row is None:
        raise AssessmentTaskError(f"loan_account {loan_account_id} not found")
    return LoanAccountRef(
        id=loan_account_id,
        tenant_id=row.tenant_id,
        external_ref=row.external_ref,
        product_type=row.product_type,
        is_microfinance=row.is_microfinance,
        is_digital_lending=row.is_digital_lending,
        device_financed=row.device_financed,
        entity_type=row.entity_type,
    )


def _row_to_fact_out(row: Any, *, loan_account_id: UUID, document_id: UUID) -> ExtractedFactOut:
    raw = row.value_normalized
    data = json.loads(raw) if isinstance(raw, str) else raw
    from pydantic import TypeAdapter

    value: FactValue | None = TypeAdapter(FactValue).validate_python(data) if data else None
    return ExtractedFactOut(
        id=row.id,
        document_id=document_id,
        loan_account_id=loan_account_id,
        field_key=row.field_key,
        value=value,
        value_raw=row.value_raw,
        is_absent=row.is_absent,
        confidence=float(row.confidence) if row.confidence is not None else 0.5,
    )


async def _assess_one_field(
    session: AsyncSession,
    *,
    fact_row: Any,
    loan_account_id: UUID,
    document_id: UUID,
    event_date: Any,
    account: LoanAccountRef,
    snapshot_id: UUID,
    settings: Settings,
    registry: FieldRegistry,
    client: LLMClient,
    request_id: str,
) -> int:
    fact = _row_to_fact_out(fact_row, loan_account_id=loan_account_id, document_id=document_id)
    results = await assess_fact(
        session=session,
        fact=fact,
        account=account,
        document_event_date=event_date,
        snapshot_id=snapshot_id,
        settings=settings,
        registry=registry,
        client=client,
        request_id=request_id,
    )
    return len(results)


async def _run_assess_document(
    document_id: UUID, tenant_id: UUID, request_id: str, *, client: LLMClient | None = None
) -> dict[str, Any]:
    settings = get_settings()
    sessionmaker = get_sessionmaker(settings)
    registry = FieldRegistry("app/schema/fields.yaml")
    client = client or LLMClient(settings)

    async with sessionmaker() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
        )
        doc_row = (
            await session.execute(text(_DOCUMENT_ROW_SQL), {"document_id": str(document_id)})
        ).first()
        if doc_row is None:
            raise AssessmentTaskError(f"document {document_id} not found")

        snapshot_id = await get_active_snapshot_id(session)
        if snapshot_id is None:
            raise AssessmentTaskError("no active corpus snapshot")

        account = await _load_account_ref(session, doc_row.loan_account_id)
        fact_rows = (
            await session.execute(text(_FACTS_FOR_DOCUMENT_SQL), {"document_id": str(document_id)})
        ).all()

        checks_run = 0
        for fact_row in fact_rows:
            checks_run += await _assess_one_field(
                session,
                fact_row=fact_row,
                loan_account_id=doc_row.loan_account_id,
                document_id=document_id,
                event_date=doc_row.event_date,
                account=account,
                snapshot_id=snapshot_id,
                settings=settings,
                registry=registry,
                client=client,
                request_id=request_id,
            )
        await session.commit()

    return {
        "document_id": str(document_id),
        "facts_assessed": len(fact_rows),
        "checks_run": checks_run,
    }


async def _run_assess_check(
    loan_account_id: UUID,
    check_key: str,
    tenant_id: UUID,
    request_id: str,
    *,
    client: LLMClient | None = None,
) -> dict[str, Any]:
    """Re-assesses the single field a conflict's `raises_check` names — scoped, never a full
    account re-run (LLD §12's own point of the `raises_check` mechanism). `check_key` is
    either `F:<field_key>` (a model-decided check) or a rule id, in which case we re-assess
    the first field that rule consumes: `assess_fact` re-evaluates every rule for that field
    internally, so re-running through any one of a firing rule's consumed fields reaches it."""
    settings = get_settings()
    sessionmaker = get_sessionmaker(settings)
    registry = FieldRegistry("app/schema/fields.yaml")
    client = client or LLMClient(settings)

    if check_key.startswith("F:"):
        field_key = check_key[len("F:") :]
    else:
        from app.rules.registry import get_rule

        rule = get_rule(check_key)
        if not rule.consumes:
            raise AssessmentTaskError(f"rule {check_key} consumes no fields")
        field_key = rule.consumes[0]

    async with sessionmaker() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
        )
        fact_row = (
            await session.execute(
                text(_LATEST_FACT_FOR_FIELD_SQL),
                {"loan_account_id": str(loan_account_id), "field_key": field_key},
            )
        ).first()
        if fact_row is None:
            raise AssessmentTaskError(
                f"no non-absent fact for field {field_key!r} on account {loan_account_id}"
            )

        doc_row = (
            await session.execute(
                text(_DOCUMENT_ROW_SQL), {"document_id": str(fact_row.document_id)}
            )
        ).first()
        if doc_row is None:
            raise AssessmentTaskError(f"document {fact_row.document_id} not found")

        snapshot_id = await get_active_snapshot_id(session)
        if snapshot_id is None:
            raise AssessmentTaskError("no active corpus snapshot")

        account = await _load_account_ref(session, loan_account_id)
        checks_run = await _assess_one_field(
            session,
            fact_row=fact_row,
            loan_account_id=loan_account_id,
            document_id=fact_row.document_id,
            event_date=doc_row.event_date,
            account=account,
            snapshot_id=snapshot_id,
            settings=settings,
            registry=registry,
            client=client,
            request_id=request_id,
        )
        await session.commit()

    return {
        "loan_account_id": str(loan_account_id),
        "check_key": check_key,
        "checks_run": checks_run,
    }


async def _run_assess_account(
    loan_account_id: UUID, tenant_id: UUID, request_id: str, *, client: LLMClient | None = None
) -> dict[str, Any]:
    settings = get_settings()
    sessionmaker = get_sessionmaker(settings)
    registry = FieldRegistry("app/schema/fields.yaml")
    client = client or LLMClient(settings)

    async with sessionmaker() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
        )
        snapshot_id = await get_active_snapshot_id(session)
        if snapshot_id is None:
            raise AssessmentTaskError("no active corpus snapshot")
        account = await _load_account_ref(session, loan_account_id)

        field_rows = (
            await session.execute(
                text(_ALL_ASSESSED_FIELD_KEYS_SQL), {"loan_account_id": str(loan_account_id)}
            )
        ).all()

        checks_run = 0
        for field_row in field_rows:
            fact_row = (
                await session.execute(
                    text(_LATEST_FACT_FOR_FIELD_SQL),
                    {"loan_account_id": str(loan_account_id), "field_key": field_row.field_key},
                )
            ).first()
            if fact_row is None:
                continue
            doc_row = (
                await session.execute(
                    text(_DOCUMENT_ROW_SQL), {"document_id": str(fact_row.document_id)}
                )
            ).first()
            if doc_row is None:
                continue
            checks_run += await _assess_one_field(
                session,
                fact_row=fact_row,
                loan_account_id=loan_account_id,
                document_id=fact_row.document_id,
                event_date=doc_row.event_date,
                account=account,
                snapshot_id=snapshot_id,
                settings=settings,
                registry=registry,
                client=client,
                request_id=request_id,
            )
        await session.commit()

    return {
        "loan_account_id": str(loan_account_id),
        "fields_assessed": len(field_rows),
        "checks_run": checks_run,
    }


@app.task(name="assess.document", bind=True)  # type: ignore[untyped-decorator]
def assess_document(self: Any, document_id: str, tenant_id: str, request_id: str) -> dict[str, Any]:
    return asyncio.run(_run_assess_document(UUID(document_id), UUID(tenant_id), request_id))


@app.task(name="assess.check", bind=True)  # type: ignore[untyped-decorator]
def assess_check(
    self: Any, loan_account_id: str, check_key: str, tenant_id: str, request_id: str
) -> dict[str, Any]:
    return asyncio.run(
        _run_assess_check(UUID(loan_account_id), check_key, UUID(tenant_id), request_id)
    )


@app.task(name="assess.account", bind=True)  # type: ignore[untyped-decorator]
def assess_account(
    self: Any, loan_account_id: str, tenant_id: str, request_id: str
) -> dict[str, Any]:
    return asyncio.run(_run_assess_account(UUID(loan_account_id), UUID(tenant_id), request_id))
