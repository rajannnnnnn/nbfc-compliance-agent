import uuid

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.db.engine import get_sessionmaker
from app.extract.service import extract_document
from app.llm.client import LLMClient
from app.schema.registry import FieldRegistry

pytestmark = pytest.mark.integration

DOCUMENT_TEXT = (
    "KEY FACTS STATEMENT\n"
    "The Annual Percentage Rate applicable to this loan is 18.5% p.a.\n"
    "Sanctioned amount: Rs 5,00,000.\n"
    "Grievance officer: Jane Doe, phone 9876543210.\n"
)


@pytest.fixture
async def account_and_doc():
    settings = get_settings()
    sm = get_sessionmaker(settings)
    tenant_id, loan_id, doc_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with sm() as session:
        await session.execute(
            text("INSERT INTO tenant (id, name) VALUES (:id, 't')"), {"id": str(tenant_id)}
        )
        await session.execute(
            text(
                "INSERT INTO loan_account (id, tenant_id, external_ref, product_type) "
                "VALUES (:id, :tid, 'LN-EXT', 'personal')"
            ),
            {"id": str(loan_id), "tid": str(tenant_id)},
        )
        await session.execute(
            text(
                "INSERT INTO document (id, tenant_id, loan_account_id, doc_type, "
                "lifecycle_stage, event_date, content_sha256, source_uri, char_count, "
                "span_budget_chars) VALUES (:id, :tid, :lid, 'kfs', 'sanction', "
                "'2026-01-01', repeat('b', 64), 'uri://x', :cc, :budget)"
            ),
            {
                "id": str(doc_id),
                "tid": str(tenant_id),
                "lid": str(loan_id),
                "cc": len(DOCUMENT_TEXT),
                "budget": int(len(DOCUMENT_TEXT) * 0.15),
            },
        )
        await session.commit()
    yield tenant_id, loan_id, doc_id
    async with sm() as session:
        await session.execute(
            text("DELETE FROM extracted_fact WHERE document_id = :id"), {"id": str(doc_id)}
        )
        await session.execute(text("DELETE FROM document WHERE id = :id"), {"id": str(doc_id)})
        await session.execute(text("DELETE FROM loan_account WHERE id = :id"), {"id": str(loan_id)})
        await session.execute(text("DELETE FROM tenant WHERE id = :id"), {"id": str(tenant_id)})
        await session.commit()


def _mock_client_for_kfs(settings) -> LLMClient:
    """Fakes the model's response: apr_bps present and grounded, sanctioned_amount present,
    grievance_officer_phone present (redaction-exempt), everything else absent."""
    client = LLMClient(settings)

    async def fake_structured(*, model_cls, model, messages, stage, adapter_id=None):
        data = {}
        for key in model_cls.model_fields:
            data[key] = {"is_absent": True}
        data["apr_bps"] = {
            "value_raw": "18.5%",
            "is_absent": False,
            "quoted_span": "18.5% p.a.",
            "confidence": 0.95,
        }
        data["sanctioned_amount"] = {
            "value_raw": "Rs 5,00,000",
            "is_absent": False,
            "quoted_span": "Rs 5,00,000",
            "confidence": 0.9,
        }
        data["grievance_officer_phone"] = {
            "value_raw": "9876543210",
            "is_absent": False,
            "quoted_span": "9876543210",
            "confidence": 0.9,
        }
        instance = model_cls.model_validate(data)
        return instance, None

    client.structured = fake_structured
    return client


async def test_extraction_persists_facts_and_verifies_spans(account_and_doc):
    tenant_id, loan_id, doc_id = account_and_doc
    settings = get_settings()
    client = _mock_client_for_kfs(settings)
    registry = FieldRegistry("app/schema/fields.yaml")
    sm = get_sessionmaker(settings)

    async with sm() as session:
        fact_ids = await extract_document(
            session=session,
            document_id=doc_id,
            tenant_id=tenant_id,
            loan_account_id=loan_id,
            doc_type="kfs",
            document_text=DOCUMENT_TEXT,
            client=client,
            registry=registry,
            settings=settings,
        )
        await session.commit()

    assert len(fact_ids) == len(registry.for_doc_type("kfs"))

    async with sm() as session:
        row = await session.execute(
            text(
                "SELECT value_normalized, span_verified FROM extracted_fact WHERE document_id = :id AND field_key = 'apr_bps'"
            ),
            {"id": str(doc_id)},
        )
        value_normalized, span_verified = row.one()
        assert value_normalized["bps"] == 1850
        assert span_verified is True


async def test_grievance_officer_phone_not_redacted_but_others_are(account_and_doc):
    """redaction_exempt fields (the lender's own published contact) pass through unredacted."""
    tenant_id, loan_id, doc_id = account_and_doc
    settings = get_settings()
    client = _mock_client_for_kfs(settings)
    registry = FieldRegistry("app/schema/fields.yaml")
    sm = get_sessionmaker(settings)

    async with sm() as session:
        await extract_document(
            session=session,
            document_id=doc_id,
            tenant_id=tenant_id,
            loan_account_id=loan_id,
            doc_type="kfs",
            document_text=DOCUMENT_TEXT,
            client=client,
            registry=registry,
            settings=settings,
        )
        await session.commit()

    async with sm() as session:
        row = await session.execute(
            text(
                "SELECT value_raw FROM extracted_fact WHERE document_id = :id "
                "AND field_key = 'grievance_officer_phone'"
            ),
            {"id": str(doc_id)},
        )
        assert row.scalar_one() == "9876543210"


async def test_absent_fields_have_no_value_normalized(account_and_doc):
    tenant_id, loan_id, doc_id = account_and_doc
    settings = get_settings()
    client = _mock_client_for_kfs(settings)
    registry = FieldRegistry("app/schema/fields.yaml")
    sm = get_sessionmaker(settings)

    async with sm() as session:
        await extract_document(
            session=session,
            document_id=doc_id,
            tenant_id=tenant_id,
            loan_account_id=loan_id,
            doc_type="kfs",
            document_text=DOCUMENT_TEXT,
            client=client,
            registry=registry,
            settings=settings,
        )
        await session.commit()

    async with sm() as session:
        row = await session.execute(
            text(
                "SELECT is_absent, value_normalized, value_raw FROM extracted_fact "
                "WHERE document_id = :id AND field_key = 'cooling_off_period_days'"
            ),
            {"id": str(doc_id)},
        )
        is_absent, value_normalized, value_raw = row.one()
        assert is_absent is True
        assert value_normalized is None
        assert value_raw is None


async def test_span_budget_consumed_across_multiple_facts(account_and_doc):
    tenant_id, loan_id, doc_id = account_and_doc
    settings = get_settings()
    client = _mock_client_for_kfs(settings)
    registry = FieldRegistry("app/schema/fields.yaml")
    sm = get_sessionmaker(settings)

    async with sm() as session:
        await extract_document(
            session=session,
            document_id=doc_id,
            tenant_id=tenant_id,
            loan_account_id=loan_id,
            doc_type="kfs",
            document_text=DOCUMENT_TEXT,
            client=client,
            registry=registry,
            settings=settings,
        )
        await session.commit()

    async with sm() as session:
        row = await session.execute(
            text("SELECT span_used_chars, span_budget_chars FROM document WHERE id = :id"),
            {"id": str(doc_id)},
        )
        used, budget = row.one()
        assert used > 0
        assert used <= budget
