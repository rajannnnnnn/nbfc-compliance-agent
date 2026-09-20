"""_run_assess_document / _run_assess_check against real Postgres. The Celery task wrappers
themselves are thin (asyncio.run + uuid parsing) — tested here via the async helpers directly,
matching every other module in this codebase's "no Celery worker needed to test the logic"
pattern (LLD §14's own point of keeping task bodies thin)."""

import json
import uuid

import pytest
from sqlalchemy import text as sqltext

from app.config import get_settings
from app.corpus.service import ingest
from app.db.engine import get_sessionmaker
from app.domain.verdicts import VerdictDraft
from app.llm.client import CallRecord, LLMClient
from app.tasks.assess_tasks import (
    AssessmentTaskError,
    _run_assess_check,
    _run_assess_document,
)

pytestmark = pytest.mark.integration


def _no_clause_found_client(settings) -> LLMClient:
    client = LLMClient(settings)

    async def _structured(*, model_cls, model, messages, stage, adapter_id=None):
        draft = VerdictDraft(
            verdict="no_clause_found",
            citations=[],
            rationale="No candidate clause governs this fact.",
            confidence_band="medium",
        )
        record = CallRecord(
            provider="openai",
            model=model,
            adapter_id=adapter_id,
            stage=stage,
            tokens_in=10,
            tokens_out=5,
            wall_clock_ms=1,
            cost_usd=0.0,
            outcome="success",
        )
        return draft, record

    async def _embed(texts, *, model, dimensions):
        return [[0.001] * dimensions for _ in texts]

    client.structured = _structured  # type: ignore[method-assign]
    client.embed = _embed  # type: ignore[method-assign]
    return client


@pytest.fixture
async def snapshot_id():
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        await session.execute(sqltext("TRUNCATE corpus_snapshot CASCADE"))
        await session.commit()
    report = await ingest(settings=settings, activate=True)
    return report.snapshot_id


@pytest.fixture
async def account_and_doc():
    settings = get_settings()
    sm = get_sessionmaker(settings)
    tenant_id, loan_id, doc_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with sm() as session:
        await session.execute(
            sqltext("INSERT INTO tenant (id, name) VALUES (:id, 't')"), {"id": str(tenant_id)}
        )
        await session.execute(
            sqltext(
                "INSERT INTO loan_account (id, tenant_id, external_ref, product_type) "
                "VALUES (:id, :tid, 'LN-TASK', 'personal')"
            ),
            {"id": str(loan_id), "tid": str(tenant_id)},
        )
        await session.execute(
            sqltext(
                "INSERT INTO document (id, tenant_id, loan_account_id, doc_type, "
                "lifecycle_stage, event_date, content_sha256, source_uri, char_count, "
                "span_budget_chars) VALUES (:id, :tid, :lid, 'docs_release_ack', 'closure', "
                "'2026-04-12', repeat('e', 64), 'uri://x', 100, 15)"
            ),
            {"id": str(doc_id), "tid": str(tenant_id), "lid": str(loan_id)},
        )
        await session.commit()
    yield tenant_id, loan_id, doc_id
    async with sm() as session:
        await session.execute(
            sqltext(
                "DELETE FROM assessment_citation WHERE assessment_id IN "
                "(SELECT id FROM assessment WHERE loan_account_id = :lid)"
            ),
            {"lid": str(loan_id)},
        )
        await session.execute(
            sqltext("DELETE FROM assessment WHERE loan_account_id = :lid"), {"lid": str(loan_id)}
        )
        await session.execute(
            sqltext("DELETE FROM loan_compliance_state WHERE loan_account_id = :lid"),
            {"lid": str(loan_id)},
        )
        await session.execute(
            sqltext("DELETE FROM extracted_fact WHERE loan_account_id = :lid"),
            {"lid": str(loan_id)},
        )
        await session.execute(sqltext("DELETE FROM document WHERE id = :id"), {"id": str(doc_id)})
        await session.execute(
            sqltext("DELETE FROM loan_account WHERE id = :id"), {"id": str(loan_id)}
        )
        await session.execute(sqltext("DELETE FROM tenant WHERE id = :id"), {"id": str(tenant_id)})
        await session.commit()


async def _insert_fact(session, *, tenant_id, document_id, loan_account_id, field_key, value_json):
    await session.execute(
        sqltext("""
            INSERT INTO extracted_fact
                (id, tenant_id, document_id, loan_account_id, field_key, value_type,
                 value_raw, value_normalized, is_absent, confidence, extraction_run_id)
            VALUES
                (:id, :tid, :did, :lid, :fk, 'date', 'x', CAST(:vn AS jsonb), false, 0.9, :run)
            """),
        {
            "id": str(uuid.uuid4()),
            "tid": str(tenant_id),
            "did": str(document_id),
            "lid": str(loan_account_id),
            "fk": field_key,
            "vn": json.dumps(value_json),
            "run": str(uuid.uuid4()),
        },
    )


async def test_assess_document_runs_a_check_for_every_non_absent_fact(snapshot_id, account_and_doc):
    tenant_id, loan_id, doc_id = account_and_doc
    settings = get_settings()
    sm = get_sessionmaker(settings)

    async with sm() as session:
        await _insert_fact(
            session,
            tenant_id=tenant_id,
            document_id=doc_id,
            loan_account_id=loan_id,
            field_key="full_repayment_date",
            value_json={"kind": "date", "v": "2026-03-02"},
        )
        await _insert_fact(
            session,
            tenant_id=tenant_id,
            document_id=doc_id,
            loan_account_id=loan_id,
            field_key="original_docs_released_date",
            value_json={"kind": "date", "v": "2026-04-12"},
        )
        await session.commit()

    result = await _run_assess_document(
        doc_id, tenant_id, "req-task-1", client=_no_clause_found_client(settings)
    )
    assert result["facts_assessed"] == 2
    assert result["checks_run"] >= 2  # R01 fires (shadow) for one field; both hit the model too

    async with sm() as session:
        count = (
            await session.execute(
                sqltext("SELECT COUNT(*) FROM assessment WHERE loan_account_id = :lid"),
                {"lid": str(loan_id)},
            )
        ).scalar_one()
        assert count == result["checks_run"]


async def test_assess_document_missing_document_raises(snapshot_id):
    with pytest.raises(AssessmentTaskError):
        await _run_assess_document(uuid.uuid4(), uuid.uuid4(), "req-task-2")


async def test_assess_check_rescopes_to_one_field(snapshot_id, account_and_doc):
    """A model-decided check_key (F:field_key) re-runs only that field, not the whole
    document — proving the scoping LLD §12 requires for a conflict-triggered re-assessment."""
    tenant_id, loan_id, doc_id = account_and_doc
    settings = get_settings()
    sm = get_sessionmaker(settings)

    async with sm() as session:
        await _insert_fact(
            session,
            tenant_id=tenant_id,
            document_id=doc_id,
            loan_account_id=loan_id,
            field_key="closure_statement_date",
            value_json={"kind": "date", "v": "2026-05-01"},
        )
        await session.commit()

    result = await _run_assess_check(
        loan_id,
        "F:closure_statement_date",
        tenant_id,
        "req-task-3",
        client=_no_clause_found_client(settings),
    )
    assert result["checks_run"] == 1

    async with sm() as session:
        row = (
            await session.execute(
                sqltext("SELECT field_key FROM assessment WHERE loan_account_id = :lid"),
                {"lid": str(loan_id)},
            )
        ).one()
        assert row.field_key == "closure_statement_date"


async def test_assess_check_missing_fact_raises(snapshot_id, account_and_doc):
    tenant_id, loan_id, _doc_id = account_and_doc
    with pytest.raises(AssessmentTaskError):
        await _run_assess_check(loan_id, "F:closure_statement_date", tenant_id, "req-task-4")
