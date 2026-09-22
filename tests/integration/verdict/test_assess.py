"""M6-T01: verdict orchestration against the real ingested placeholder corpus."""

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
from app.domain.verdicts import Citation, VerdictDraft
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
                "VALUES (:id, :tid, 'LN-ASSESS', 'personal')"
            ),
            {"id": str(loan_id), "tid": str(tenant_id)},
        )
        await session.execute(
            sqltext(
                "INSERT INTO document (id, tenant_id, loan_account_id, doc_type, "
                "lifecycle_stage, event_date, content_sha256, source_uri, char_count, "
                "span_budget_chars) VALUES (:id, :tid, :lid, 'docs_release_ack', 'closure', "
                "'2026-04-12', repeat('a', 64), 'uri://x', 100, 15)"
            ),
            {"id": str(doc_id), "tid": str(tenant_id), "lid": str(loan_id)},
        )
        await session.commit()
    ref = LoanAccountRef(
        id=loan_id,
        tenant_id=tenant_id,
        external_ref="LN-ASSESS",
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


def _raising_client(settings) -> LLMClient:
    client = LLMClient(settings)

    async def _boom(*args, **kwargs):
        raise AssertionError("model must not be called when a rule short-circuits")

    client.structured = _boom  # type: ignore[method-assign]
    return client


def _no_clause_found_client(settings) -> LLMClient:
    client = LLMClient(settings)

    async def _structured(*, model_cls, model, messages, stage, adapter_id=None):
        draft = VerdictDraft(
            verdict="no_clause_found",
            citations=[],
            rationale="No candidate clause governs a closure statement's own issue date.",
            confidence_band="medium",
        )
        record = CallRecord(
            provider="openai",
            model=model,
            adapter_id=adapter_id,
            stage=stage,
            tokens_in=100,
            tokens_out=40,
            wall_clock_ms=5,
            cost_usd=0.0001,
            outcome="success",
        )
        return draft, record

    async def _embed(texts, *, model, dimensions):
        return [[0.001] * dimensions for _ in texts]

    client.structured = _structured  # type: ignore[method-assign]
    client.embed = _embed  # type: ignore[method-assign]
    return client


async def _seed_r01_facts(session, *, ref, doc_id):
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


async def test_shadow_rule_persists_and_does_not_suppress_model(snapshot_id, account):
    """LLD §11.2 / M6-T01: with the placeholder corpus, RBC2025 is not `rbi_verified`, so R01
    fires in shadow mode. A shadow firing must still be persisted (is_shadow=True,
    decided_by='shadow') AND must NOT suppress the model path for the same field — the model
    is still asked and its own (validated) result is persisted alongside."""
    ref, doc_id = account
    settings = get_settings()
    sm = get_sessionmaker(settings)
    registry = FieldRegistry("app/schema/fields.yaml")

    async with sm() as session:
        await _seed_r01_facts(session, ref=ref, doc_id=doc_id)

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

        results = await assess_fact(
            session=session,
            fact=fact,
            account=ref,
            document_event_date=date(2026, 4, 12),
            snapshot_id=snapshot_id,
            settings=settings,
            registry=registry,
            client=_no_clause_found_client(settings),
            request_id="req-test-1",
        )
        await session.commit()

    shadow_results = [r for r in results if r.decided_by == "shadow"]
    model_results = [r for r in results if r.decided_by == "model"]
    assert model_results  # the model path still ran despite shadow firings

    r01_result = next(r for r in shadow_results if r.rule_id == "R01_docs_release_30d")
    assert r01_result.verdict == "violation"
    assert r01_result.is_shadow is True
    assert r01_result.severity == "critical"
    assert r01_result.citations[0].clause_path == "RBC2025/p35"

    async with sm() as session:
        rows = (
            await session.execute(
                sqltext(
                    "SELECT verdict, decided_by, is_shadow FROM assessment "
                    "WHERE loan_account_id = :lid ORDER BY decided_by"
                ),
                {"lid": str(ref.id)},
            )
        ).all()
        assert len(rows) == len(results)

        cite_row = (
            await session.execute(
                sqltext(
                    "SELECT ac.clause_path, c.clause_path AS real_path FROM assessment_citation ac "
                    "JOIN clause c ON c.id = ac.clause_id WHERE ac.clause_path = 'RBC2025/p35'"
                )
            )
        ).one()
        assert cite_row.clause_path == cite_row.real_path


async def test_verified_rule_short_circuits_model_call(snapshot_id, account):
    """M6-T01: once an instrument is `rbi_verified` (the state the real corpus will be in
    after go-live), a firing rule based on it is no longer shadow and must short-circuit the
    model call entirely."""
    ref, doc_id = account
    settings = get_settings()
    sm = get_sessionmaker(settings)
    registry = FieldRegistry("app/schema/fields.yaml")

    async with sm() as session:
        await session.execute(
            sqltext(
                "UPDATE regulation_instrument SET verification_status = 'rbi_verified' "
                "WHERE snapshot_id = :sid AND code = 'RBC2025'"
            ),
            {"sid": str(snapshot_id)},
        )
        await _seed_r01_facts(session, ref=ref, doc_id=doc_id)

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

        results = await assess_fact(
            session=session,
            fact=fact,
            account=ref,
            document_event_date=date(2026, 4, 12),
            snapshot_id=snapshot_id,
            settings=settings,
            registry=registry,
            client=_raising_client(settings),
            request_id="req-test-1b",
        )
        await session.commit()

    assert results  # the raising client would have blown up if the model path ran
    assert all(r.decided_by == "rule" for r in results)
    result = next(r for r in results if r.rule_id == "R01_docs_release_30d")
    assert result.is_shadow is False
    assert result.verdict == "violation"
    assert result.severity == "critical"
    assert result.citations[0].clause_path == "RBC2025/p35"

    async with sm() as session:
        rows = (
            await session.execute(
                sqltext("SELECT verdict, decided_by FROM assessment WHERE loan_account_id = :lid"),
                {"lid": str(ref.id)},
            )
        ).all()
        assert all(row.decided_by == "rule" for row in rows)


async def test_no_rule_falls_through_to_model_and_persists(snapshot_id, account):
    """M6-T01: a field with zero rule consumers falls through to retrieval + model."""
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
            field_key="closure_statement_date",
            value_type="date",
            value_json={"kind": "date", "v": "2026-05-01"},
        )
        await session.commit()

        fact = ExtractedFactOut(
            id=uuid.uuid4(),
            document_id=doc_id,
            loan_account_id=ref.id,
            field_key="closure_statement_date",
            value=DateValue(v=date(2026, 5, 1)),
            value_raw="01/05/2026",
            is_absent=False,
            confidence=0.9,
        )

        results = await assess_fact(
            session=session,
            fact=fact,
            account=ref,
            document_event_date=date(2026, 5, 1),
            snapshot_id=snapshot_id,
            settings=settings,
            registry=registry,
            client=_no_clause_found_client(settings),
            request_id="req-test-2",
        )
        await session.commit()

    assert len(results) == 1
    result = results[0]
    assert result.decided_by == "model"
    assert result.verdict == "no_clause_found"
    assert result.severity == "informational"
    assert result.check_key == "F:closure_statement_date"
    assert result.citations == []

    async with sm() as session:
        row = (
            await session.execute(
                sqltext(
                    "SELECT verdict, decided_by, corpus_snapshot_id FROM assessment "
                    "WHERE loan_account_id = :lid"
                ),
                {"lid": str(ref.id)},
            )
        ).one()
        assert row.verdict == "no_clause_found"
        assert row.decided_by == "model"
        assert str(row.corpus_snapshot_id) == str(snapshot_id)


async def test_bad_citation_is_rejected_and_audited(snapshot_id, account):
    """SQ-18/ADR-025: a model citing a path never offered downgrades to no_clause_found and
    writes a citation_rejected audit event — the guardrail runs even when nothing fires."""
    ref, doc_id = account
    settings = get_settings()
    sm = get_sessionmaker(settings)
    registry = FieldRegistry("app/schema/fields.yaml")

    def _bad_citation_client(settings) -> LLMClient:
        client = LLMClient(settings)

        async def _structured(*, model_cls, model, messages, stage, adapter_id=None):
            draft = VerdictDraft(
                verdict="violation",
                citations=[
                    Citation(
                        clause_path="RBC2025/p999_not_real",
                        role="decisive",
                        quoted_clause_excerpt="fabricated text",
                    )
                ],
                rationale="hallucinated basis",
                confidence_band="high",
            )
            record = CallRecord(
                provider="openai",
                model=model,
                adapter_id=adapter_id,
                stage=stage,
                tokens_in=50,
                tokens_out=20,
                wall_clock_ms=3,
                cost_usd=0.0,
                outcome="success",
            )
            return draft, record

        async def _embed(texts, *, model, dimensions):
            return [[0.001] * dimensions for _ in texts]

        client.structured = _structured  # type: ignore[method-assign]
        client.embed = _embed  # type: ignore[method-assign]
        return client

    async with sm() as session:
        await _insert_fact(
            session,
            tenant_id=ref.tenant_id,
            document_id=doc_id,
            loan_account_id=ref.id,
            field_key="closure_statement_date",
            value_type="date",
            value_json={"kind": "date", "v": "2026-05-01"},
        )
        await session.commit()

        fact = ExtractedFactOut(
            id=uuid.uuid4(),
            document_id=doc_id,
            loan_account_id=ref.id,
            field_key="closure_statement_date",
            value=DateValue(v=date(2026, 5, 1)),
            value_raw="01/05/2026",
            is_absent=False,
            confidence=0.9,
        )

        results = await assess_fact(
            session=session,
            fact=fact,
            account=ref,
            document_event_date=date(2026, 5, 1),
            snapshot_id=snapshot_id,
            settings=settings,
            registry=registry,
            client=_bad_citation_client(settings),
            request_id="req-test-3",
        )
        await session.commit()

    assert len(results) == 1
    result = results[0]
    assert result.decided_by == "validator_downgrade"
    assert result.verdict == "no_clause_found"
    assert result.citations == []

    async with sm() as session:
        audit_row = (
            await session.execute(
                sqltext(
                    "SELECT detail FROM audit_event WHERE tenant_id = :tid "
                    "AND action = 'citation_rejected'"
                ),
                {"tid": str(ref.tenant_id)},
            )
        ).one()
        detail = (
            audit_row.detail if isinstance(audit_row.detail, dict) else json.loads(audit_row.detail)
        )
        assert detail["reason"] == "not_offered"
        assert detail["clause_path"] == "RBC2025/p999_not_real"
