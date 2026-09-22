"""M7-T03: loan_compliance_state recomputation after assess_fact."""

import json
import uuid
from datetime import date

import pytest
from sqlalchemy import text as sqltext

from app.config import get_settings
from app.corpus.service import ingest
from app.db.engine import get_sessionmaker
from app.domain.documents import LoanAccountRef
from app.domain.facts import DateValue, ExtractedFactOut
from app.domain.verdicts import VerdictDraft
from app.llm.client import CallRecord, LLMClient
from app.schema.registry import FieldRegistry
from app.verdict.assess import assess_fact

pytestmark = pytest.mark.integration


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
async def account():
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
                "VALUES (:id, :tid, 'LN-STATE', 'personal')"
            ),
            {"id": str(loan_id), "tid": str(tenant_id)},
        )
        await session.execute(
            sqltext(
                "INSERT INTO document (id, tenant_id, loan_account_id, doc_type, "
                "lifecycle_stage, event_date, content_sha256, source_uri, char_count, "
                "span_budget_chars) VALUES (:id, :tid, :lid, 'docs_release_ack', 'closure', "
                "'2026-04-12', repeat('d', 64), 'uri://x', 100, 15)"
            ),
            {"id": str(doc_id), "tid": str(tenant_id), "lid": str(loan_id)},
        )
        await session.commit()
    ref = LoanAccountRef(
        id=loan_id,
        tenant_id=tenant_id,
        external_ref="LN-STATE",
        product_type="personal",
        is_microfinance=False,
        is_digital_lending=False,
        device_financed=False,
    )
    yield ref, doc_id
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
            sqltext("DELETE FROM audit_event WHERE tenant_id = :tid"), {"tid": str(tenant_id)}
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


async def _insert_fact(
    session, *, tenant_id, document_id, loan_account_id, field_key, value_type, value_json
):
    await session.execute(
        sqltext("""
            INSERT INTO extracted_fact
                (id, tenant_id, document_id, loan_account_id, field_key, value_type,
                 value_raw, value_normalized, is_absent, confidence, extraction_run_id)
            VALUES
                (:id, :tid, :did, :lid, :fk, :vt, 'x', CAST(:vn AS jsonb), false, 0.9, :run)
            """),
        {
            "id": str(uuid.uuid4()),
            "tid": str(tenant_id),
            "did": str(document_id),
            "lid": str(loan_account_id),
            "fk": field_key,
            "vt": value_type,
            "vn": json.dumps(value_json),
            "run": str(uuid.uuid4()),
        },
    )


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


async def test_state_reflects_shadow_violation_and_excludes_it_from_open_counts(
    snapshot_id, account
):
    """R01 fires as violation but in shadow mode (placeholder corpus): loan_compliance_state's
    open_violations must stay 0 and highest_severity must stay null, because a shadow finding
    is not a citable finding. The model's own no_clause_found result IS counted."""
    ref, doc_id = account
    settings = get_settings()
    sm = get_sessionmaker(settings)
    registry = FieldRegistry("app/schema/fields.yaml")

    async with sm() as session:
        await _insert_fact(
            session,
            tenant_id=ref.tenant_id,
            document_id=doc_id,
            loan_account_id=ref.id,
            field_key="full_repayment_date",
            value_type="date",
            value_json={"kind": "date", "v": "2026-03-02"},
        )
        await _insert_fact(
            session,
            tenant_id=ref.tenant_id,
            document_id=doc_id,
            loan_account_id=ref.id,
            field_key="original_docs_released_date",
            value_type="date",
            value_json={"kind": "date", "v": "2026-04-12"},
        )
        await session.commit()

        fact = ExtractedFactOut(
            id=uuid.uuid4(),
            document_id=doc_id,
            loan_account_id=ref.id,
            field_key="original_docs_released_date",
            value=DateValue(v=date(2026, 4, 12)),
            value_raw="12/04/2026",
            is_absent=False,
            confidence=0.9,
        )

        await assess_fact(
            session=session,
            fact=fact,
            account=ref,
            document_event_date=date(2026, 4, 12),
            snapshot_id=snapshot_id,
            settings=settings,
            registry=registry,
            client=_no_clause_found_client(settings),
            request_id="req-state-1",
        )
        await session.commit()

    async with sm() as session:
        row = (
            await session.execute(
                sqltext(
                    "SELECT open_violations, open_no_clause, highest_severity, "
                    "state_version, corpus_snapshot_id FROM loan_compliance_state "
                    "WHERE loan_account_id = :lid"
                ),
                {"lid": str(ref.id)},
            )
        ).one()
        assert row.open_violations == 0  # the R01 firing was shadow — excluded
        assert row.open_no_clause == 1  # the model's own result counts
        assert row.highest_severity == "informational"
        assert row.state_version == 1
        assert str(row.corpus_snapshot_id) == str(snapshot_id)


async def test_state_version_increments_on_recomputation(snapshot_id, account):
    ref, doc_id = account
    settings = get_settings()
    sm = get_sessionmaker(settings)
    registry = FieldRegistry("app/schema/fields.yaml")

    async def _assess(field_key, value_json, req_id):
        async with sm() as session:
            await _insert_fact(
                session,
                tenant_id=ref.tenant_id,
                document_id=doc_id,
                loan_account_id=ref.id,
                field_key=field_key,
                value_type="date",
                value_json=value_json,
            )
            await session.commit()

            fact = ExtractedFactOut(
                id=uuid.uuid4(),
                document_id=doc_id,
                loan_account_id=ref.id,
                field_key=field_key,
                value=DateValue(v=date.fromisoformat(value_json["v"])),
                value_raw=value_json["v"],
                is_absent=False,
                confidence=0.9,
            )
            await assess_fact(
                session=session,
                fact=fact,
                account=ref,
                document_event_date=date.fromisoformat(value_json["v"]),
                snapshot_id=snapshot_id,
                settings=settings,
                registry=registry,
                client=_no_clause_found_client(settings),
                request_id=req_id,
            )
            await session.commit()

    await _assess("closure_statement_date", {"kind": "date", "v": "2026-05-01"}, "req-v1")
    await _assess("closure_statement_date", {"kind": "date", "v": "2026-06-01"}, "req-v2")

    async with sm() as session:
        row = (
            await session.execute(
                sqltext(
                    "SELECT state_version FROM loan_compliance_state WHERE loan_account_id = :lid"
                ),
                {"lid": str(ref.id)},
            )
        ).one()
        assert row.state_version == 2
