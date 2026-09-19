import asyncio
import uuid

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.db.engine import get_sessionmaker
from app.db.rls import require_tenant_scope
from app.extract.spans import admit_span

pytestmark = pytest.mark.integration


@pytest.fixture
async def document_row():
    settings = get_settings()
    sm = get_sessionmaker(settings)
    tenant_id = uuid.uuid4()
    loan_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    async with sm() as session:
        await session.execute(
            text("INSERT INTO tenant (id, name) VALUES (:id, 't')"), {"id": str(tenant_id)}
        )
        await session.execute(
            text(
                "INSERT INTO loan_account (id, tenant_id, external_ref, product_type) "
                "VALUES (:id, :tid, 'LN-SPAN', 'personal')"
            ),
            {"id": str(loan_id), "tid": str(tenant_id)},
        )
        # char_count=1000, span_budget_ratio applied by caller — store budget directly
        await session.execute(
            text(
                "INSERT INTO document (id, tenant_id, loan_account_id, doc_type, "
                "lifecycle_stage, event_date, content_sha256, source_uri, char_count, "
                "span_budget_chars) VALUES (:id, :tid, :lid, 'kfs', 'sanction', "
                "'2026-01-01', repeat('a', 64), 'uri://x', 1000, 100)"
            ),
            {"id": str(doc_id), "tid": str(tenant_id), "lid": str(loan_id)},
        )
        await session.commit()
    yield tenant_id, doc_id
    async with sm() as session:
        await session.execute(text("DELETE FROM document WHERE id = :id"), {"id": str(doc_id)})
        await session.execute(text("DELETE FROM loan_account WHERE id = :id"), {"id": str(loan_id)})
        await session.execute(text("DELETE FROM tenant WHERE id = :id"), {"id": str(tenant_id)})
        await session.commit()


async def test_span_within_budget_admitted(document_row):
    tenant_id, doc_id = document_row
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        await require_tenant_scope(session, tenant_id)
        admitted, truncated = await admit_span(
            session, document_id=str(doc_id), span_len=50, settings=settings
        )
        await session.commit()
    assert admitted is True
    assert truncated is False


async def test_span_exceeding_budget_is_truncated(document_row):
    tenant_id, doc_id = document_row
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        await require_tenant_scope(session, tenant_id)
        admitted, truncated = await admit_span(
            session, document_id=str(doc_id), span_len=150, settings=settings
        )
        await session.commit()
    assert admitted is True
    assert truncated is True


async def test_budget_exhaustion_rejects_further_spans(document_row):
    tenant_id, doc_id = document_row
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        await require_tenant_scope(session, tenant_id)
        await admit_span(session, document_id=str(doc_id), span_len=100, settings=settings)
        await session.commit()
    async with sm() as session:
        await require_tenant_scope(session, tenant_id)
        admitted, truncated = await admit_span(
            session, document_id=str(doc_id), span_len=10, settings=settings
        )
        await session.commit()
    assert admitted is False


async def test_concurrent_writers_cannot_exceed_budget(document_row):
    """Two concurrent admits totalling more than the budget must not both succeed at full
    length — the row lock serialises them."""
    tenant_id, doc_id = document_row
    settings = get_settings()
    sm = get_sessionmaker(settings)

    async def _admit(span_len: int) -> tuple[bool, bool]:
        async with sm() as session:
            await require_tenant_scope(session, tenant_id)
            result = await admit_span(
                session, document_id=str(doc_id), span_len=span_len, settings=settings
            )
            await session.commit()
            return result

    results = await asyncio.gather(_admit(70), _admit(70))
    admitted_lengths = []
    for (admitted, truncated), requested in zip(results, [70, 70], strict=True):
        assert admitted is True
        admitted_lengths.append(requested if not truncated else None)

    async with sm() as session:
        await require_tenant_scope(session, tenant_id)
        row = await session.execute(
            text("SELECT span_used_chars FROM document WHERE id = :id"), {"id": str(doc_id)}
        )
        used = row.scalar_one()
    assert used <= 100
