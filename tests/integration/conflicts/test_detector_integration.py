"""M7-T02: cross-document conflict detection against real persisted extracted_fact rows."""

import json
import uuid
from datetime import date

import pytest
from sqlalchemy import text as sqltext

from app.config import get_settings
from app.conflicts.detector import detect_for_fact, persist_conflicts
from app.conflicts.loader import load
from app.db.engine import get_sessionmaker
from app.domain.facts import DateValue, ExtractedFactOut, RateValue

pytestmark = pytest.mark.integration


@pytest.fixture
async def tenant_and_loan():
    settings = get_settings()
    sm = get_sessionmaker(settings)
    tenant_id, loan_id = uuid.uuid4(), uuid.uuid4()
    async with sm() as session:
        await session.execute(
            sqltext("INSERT INTO tenant (id, name) VALUES (:id, 't')"), {"id": str(tenant_id)}
        )
        await session.execute(
            sqltext(
                "INSERT INTO loan_account (id, tenant_id, external_ref, product_type) "
                "VALUES (:id, :tid, 'LN-CONFLICT', 'personal')"
            ),
            {"id": str(loan_id), "tid": str(tenant_id)},
        )
        await session.commit()
    yield tenant_id, loan_id
    async with sm() as session:
        await session.execute(
            sqltext("DELETE FROM fact_conflict WHERE loan_account_id = :lid"),
            {"lid": str(loan_id)},
        )
        await session.execute(
            sqltext("DELETE FROM extracted_fact WHERE loan_account_id = :lid"),
            {"lid": str(loan_id)},
        )
        await session.execute(
            sqltext("DELETE FROM document WHERE loan_account_id = :lid"), {"lid": str(loan_id)}
        )
        await session.execute(
            sqltext("DELETE FROM loan_account WHERE id = :id"), {"id": str(loan_id)}
        )
        await session.execute(sqltext("DELETE FROM tenant WHERE id = :id"), {"id": str(tenant_id)})
        await session.commit()


async def _insert_doc_and_fact(
    session,
    *,
    tenant_id,
    loan_account_id,
    doc_type,
    lifecycle_stage,
    field_key,
    value_type,
    value_json,
):
    doc_id = uuid.uuid4()
    sha256 = uuid.uuid4().hex + uuid.uuid4().hex  # 64 hex chars, unique per document
    await session.execute(
        sqltext(
            "INSERT INTO document (id, tenant_id, loan_account_id, doc_type, lifecycle_stage, "
            "event_date, content_sha256, source_uri, char_count, span_budget_chars) VALUES "
            "(:id, :tid, :lid, :dt, :ls, '2026-01-01', :sha, 'uri://x', 10, 2)"
        ),
        {
            "id": str(doc_id),
            "tid": str(tenant_id),
            "lid": str(loan_account_id),
            "dt": doc_type,
            "sha": sha256,
            "ls": lifecycle_stage,
        },
    )
    fact_id = uuid.uuid4()
    await session.execute(
        sqltext("""
            INSERT INTO extracted_fact
                (id, tenant_id, document_id, loan_account_id, field_key, value_type,
                 value_raw, value_normalized, is_absent, confidence, extraction_run_id)
            VALUES
                (:id, :tid, :did, :lid, :fk, :vt, 'x', CAST(:vn AS jsonb), false, 0.9, :run)
            """),
        {
            "id": str(fact_id),
            "tid": str(tenant_id),
            "did": str(doc_id),
            "lid": str(loan_account_id),
            "fk": field_key,
            "vt": value_type,
            "vn": json.dumps(value_json),
            "run": str(uuid.uuid4()),
        },
    )
    return doc_id, fact_id


async def test_apr_mismatch_detected_across_kfs_and_loan_agreement(tenant_and_loan):
    tenant_id, loan_id = tenant_and_loan
    settings = get_settings()
    sm = get_sessionmaker(settings)
    registry = load()

    async with sm() as session:
        # loan_agreement's apr_bps is on record first, at a different rate.
        await _insert_doc_and_fact(
            session,
            tenant_id=tenant_id,
            loan_account_id=loan_id,
            doc_type="loan_agreement",
            lifecycle_stage="sanction",
            field_key="apr_bps",
            value_type="rate_bps",
            value_json={"kind": "rate_bps", "bps": 1900},
        )
        await session.commit()

        _, kfs_fact_id = await _insert_doc_and_fact(
            session,
            tenant_id=tenant_id,
            loan_account_id=loan_id,
            doc_type="kfs",
            lifecycle_stage="sanction",
            field_key="apr_bps",
            value_type="rate_bps",
            value_json={"kind": "rate_bps", "bps": 1850},
        )
        await session.commit()

        fact = ExtractedFactOut(
            id=kfs_fact_id,
            document_id=uuid.uuid4(),
            loan_account_id=loan_id,
            field_key="apr_bps",
            value=RateValue(bps=1850),
            value_raw="18.5%",
            is_absent=False,
            confidence=0.9,
        )

        conflicts = await detect_for_fact(
            session=session, fact=fact, doc_type="kfs", registry=registry
        )
        assert len(conflicts) == 1
        assert conflicts[0].group_key == "apr"
        assert conflicts[0].raises_check == "R03_apr_consistency"
        assert conflicts[0].delta["diff"] == -50

        ids = await persist_conflicts(
            session, tenant_id=tenant_id, loan_account_id=loan_id, conflicts=conflicts
        )
        await session.commit()
        assert len(ids) == 1

    async with sm() as session:
        row = (
            await session.execute(
                sqltext("SELECT group_key, conflict_type FROM fact_conflict WHERE id = :id"),
                {"id": str(ids[0])},
            )
        ).one()
        assert row.group_key == "apr"
        assert row.conflict_type == "tolerance_breach"


async def test_apr_within_tolerance_is_not_a_conflict(tenant_and_loan):
    tenant_id, loan_id = tenant_and_loan
    settings = get_settings()
    sm = get_sessionmaker(settings)
    registry = load()

    async with sm() as session:
        await _insert_doc_and_fact(
            session,
            tenant_id=tenant_id,
            loan_account_id=loan_id,
            doc_type="loan_agreement",
            lifecycle_stage="sanction",
            field_key="apr_bps",
            value_type="rate_bps",
            value_json={"kind": "rate_bps", "bps": 1850},
        )
        await session.commit()

        _, kfs_fact_id = await _insert_doc_and_fact(
            session,
            tenant_id=tenant_id,
            loan_account_id=loan_id,
            doc_type="kfs",
            lifecycle_stage="sanction",
            field_key="apr_bps",
            value_type="rate_bps",
            value_json={"kind": "rate_bps", "bps": 1850},
        )
        await session.commit()

        fact = ExtractedFactOut(
            id=kfs_fact_id,
            document_id=uuid.uuid4(),
            loan_account_id=loan_id,
            field_key="apr_bps",
            value=RateValue(bps=1850),
            value_raw="18.5%",
            is_absent=False,
            confidence=0.9,
        )

        conflicts = await detect_for_fact(
            session=session, fact=fact, doc_type="kfs", registry=registry
        )
        assert conflicts == []


async def test_no_counterpart_document_yields_no_conflict(tenant_and_loan):
    tenant_id, loan_id = tenant_and_loan
    settings = get_settings()
    sm = get_sessionmaker(settings)
    registry = load()

    async with sm() as session:
        _, kfs_fact_id = await _insert_doc_and_fact(
            session,
            tenant_id=tenant_id,
            loan_account_id=loan_id,
            doc_type="kfs",
            lifecycle_stage="sanction",
            field_key="apr_bps",
            value_type="rate_bps",
            value_json={"kind": "rate_bps", "bps": 1850},
        )
        await session.commit()

        fact = ExtractedFactOut(
            id=kfs_fact_id,
            document_id=uuid.uuid4(),
            loan_account_id=loan_id,
            field_key="apr_bps",
            value=RateValue(bps=1850),
            value_raw="18.5%",
            is_absent=False,
            confidence=0.9,
        )

        conflicts = await detect_for_fact(
            session=session, fact=fact, doc_type="kfs", registry=registry
        )
        assert conflicts == []


async def test_closure_release_window_date_order_conflict(tenant_and_loan):
    """PRD-flavoured case: docs released 41 days after full repayment breaches the 30-day
    window — the same fact pattern R01 checks, now detected as a cross-document conflict."""
    tenant_id, loan_id = tenant_and_loan
    settings = get_settings()
    sm = get_sessionmaker(settings)
    registry = load()

    async with sm() as session:
        await _insert_doc_and_fact(
            session,
            tenant_id=tenant_id,
            loan_account_id=loan_id,
            doc_type="closure_statement",
            lifecycle_stage="closure",
            field_key="full_repayment_date",
            value_type="date",
            value_json={"kind": "date", "v": "2026-03-02"},
        )
        await session.commit()

        _, ack_fact_id = await _insert_doc_and_fact(
            session,
            tenant_id=tenant_id,
            loan_account_id=loan_id,
            doc_type="docs_release_ack",
            lifecycle_stage="closure",
            field_key="original_docs_released_date",
            value_type="date",
            value_json={"kind": "date", "v": "2026-04-12"},
        )
        await session.commit()

        fact = ExtractedFactOut(
            id=ack_fact_id,
            document_id=uuid.uuid4(),
            loan_account_id=loan_id,
            field_key="original_docs_released_date",
            value=DateValue(v=date(2026, 4, 12)),
            value_raw="12/04/2026",
            is_absent=False,
            confidence=0.9,
        )

        conflicts = await detect_for_fact(
            session=session, fact=fact, doc_type="docs_release_ack", registry=registry
        )
        assert len(conflicts) == 1
        assert conflicts[0].group_key == "closure_release_window"
        assert conflicts[0].raises_check == "R01_docs_release_30d"
        assert conflicts[0].delta["days"] == 41
