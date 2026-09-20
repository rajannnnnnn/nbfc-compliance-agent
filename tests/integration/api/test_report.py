"""M7-T04: GET /v1/loans/{id}/report — both json and pdf formats carry the synthetic-data
banner and the not-legal-advice disclaimer (PRD §6.3), and every finding's clause path,
instrument, effective window and verification_status."""

import hashlib
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sqltext

from app.api.deps import get_llm_client, hash_token
from app.config import get_settings
from app.corpus.service import ingest
from app.db.engine import get_sessionmaker
from app.main import app

pytestmark = pytest.mark.integration

KFS_TEXT = (
    "KEY FACTS STATEMENT\n"
    "The Annual Percentage Rate applicable to this loan is 18.5% p.a.\n"
    "Sanctioned amount: Rs 5,00,000.\n"
)


def _stub_client(settings):
    from app.domain.verdicts import VerdictDraft
    from app.llm.client import CallRecord, LLMClient

    client = LLMClient(settings)

    async def _structured(*, model_cls, model, messages, stage, adapter_id=None):
        if model_cls.__name__ == "ClassificationResult":
            data = {"doc_type": "kfs", "confidence": 0.95, "reason": "clearly a KFS"}
            return model_cls.model_validate(data), CallRecord(
                provider="openai",
                model=model,
                adapter_id=adapter_id,
                stage=stage,
                tokens_in=5,
                tokens_out=5,
                wall_clock_ms=1,
                cost_usd=0.0,
                outcome="success",
            )
        if model_cls is VerdictDraft:
            draft = VerdictDraft(
                verdict="no_clause_found",
                citations=[],
                rationale="No candidate clause governs this fact.",
                confidence_band="medium",
            )
            return draft, CallRecord(
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
        data = {key: {"is_absent": True} for key in model_cls.model_fields}
        return model_cls.model_validate(data), CallRecord(
            provider="openai",
            model=model,
            adapter_id=adapter_id,
            stage=stage,
            tokens_in=50,
            tokens_out=20,
            wall_clock_ms=1,
            cost_usd=0.0,
            outcome="success",
        )

    async def _embed(texts, *, model, dimensions):
        return [[0.001] * dimensions for _ in texts]

    client.structured = _structured  # type: ignore[method-assign]
    client.embed = _embed  # type: ignore[method-assign]
    return client


@pytest.fixture
async def active_snapshot():
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        await session.execute(sqltext("TRUNCATE corpus_snapshot CASCADE"))
        await session.commit()
    return await ingest(settings=settings, activate=True)


@pytest.fixture
async def tenant():
    settings = get_settings()
    sm = get_sessionmaker(settings)
    tenant_id = uuid.uuid4()
    raw_token = f"test-token-{uuid.uuid4()}"
    async with sm() as session:
        await session.execute(
            sqltext("INSERT INTO tenant (id, name, api_key_hash) VALUES (:id, 't', :hash)"),
            {"id": str(tenant_id), "hash": hash_token(raw_token)},
        )
        await session.commit()
    yield tenant_id, raw_token
    async with sm() as session:
        await session.execute(
            sqltext("DELETE FROM idempotency_key WHERE tenant_id = :id"), {"id": str(tenant_id)}
        )
        await session.execute(
            sqltext(
                "DELETE FROM assessment_citation WHERE assessment_id IN "
                "(SELECT a.id FROM assessment a JOIN loan_account la ON la.id = a.loan_account_id "
                "WHERE la.tenant_id = :id)"
            ),
            {"id": str(tenant_id)},
        )
        await session.execute(
            sqltext(
                "DELETE FROM assessment WHERE loan_account_id IN "
                "(SELECT id FROM loan_account WHERE tenant_id = :id)"
            ),
            {"id": str(tenant_id)},
        )
        await session.execute(
            sqltext(
                "DELETE FROM loan_compliance_state WHERE loan_account_id IN "
                "(SELECT id FROM loan_account WHERE tenant_id = :id)"
            ),
            {"id": str(tenant_id)},
        )
        await session.execute(
            sqltext(
                "DELETE FROM extracted_fact WHERE loan_account_id IN "
                "(SELECT id FROM loan_account WHERE tenant_id = :id)"
            ),
            {"id": str(tenant_id)},
        )
        await session.execute(
            sqltext(
                "DELETE FROM document WHERE loan_account_id IN "
                "(SELECT id FROM loan_account WHERE tenant_id = :id)"
            ),
            {"id": str(tenant_id)},
        )
        await session.execute(
            sqltext("DELETE FROM loan_account WHERE tenant_id = :id"), {"id": str(tenant_id)}
        )
        await session.execute(sqltext("DELETE FROM tenant WHERE id = :id"), {"id": str(tenant_id)})
        await session.commit()


@pytest.fixture(autouse=True)
def _override_llm_client():
    settings = get_settings()
    app.dependency_overrides[get_llm_client] = lambda: _stub_client(settings)
    yield
    app.dependency_overrides.pop(get_llm_client, None)


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth_headers(raw_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_token}"}


async def test_report_json_has_disclaimer_and_synthetic_banner(active_snapshot, tenant):
    _tenant_id, raw_token = tenant
    async with await _client() as client:
        r = await client.post(
            "/v1/loans",
            json={"external_ref": "LN-REPORT-1", "product_type": "personal"},
            headers=_auth_headers(raw_token),
        )
        loan_id = r.json()["id"]

        content = KFS_TEXT
        sha = hashlib.sha256(content.encode()).hexdigest()
        await client.post(
            f"/v1/loans/{loan_id}/documents",
            json={
                "event_date": "2026-04-01",
                "source_uri": "lms://test/doc1",
                "content_sha256": sha,
                "text": content,
                "is_synthetic": True,
                "assess": False,
            },
            headers=_auth_headers(raw_token),
        )

        r2 = await client.get(f"/v1/loans/{loan_id}/report", headers=_auth_headers(raw_token))
        assert r2.status_code == 200
        body = r2.json()
        assert "not legal advice" in body["disclaimer"].lower()
        assert body["synthetic_data_banner"].startswith("SYNTHETIC DATA")
        assert body["loan_account"]["external_ref"] == "LN-REPORT-1"
        assert body["findings"] == []


async def test_report_pdf_format_returns_pdf_bytes(active_snapshot, tenant):
    _tenant_id, raw_token = tenant
    async with await _client() as client:
        r = await client.post(
            "/v1/loans",
            json={"external_ref": "LN-REPORT-2", "product_type": "personal"},
            headers=_auth_headers(raw_token),
        )
        loan_id = r.json()["id"]

        r2 = await client.get(
            f"/v1/loans/{loan_id}/report",
            params={"format": "pdf"},
            headers=_auth_headers(raw_token),
        )
        assert r2.status_code == 200
        assert r2.headers["content-type"] == "application/pdf"
        assert r2.content.startswith(b"%PDF")


async def test_report_loan_not_found_is_404(active_snapshot, tenant):
    _tenant_id, raw_token = tenant
    async with await _client() as client:
        r = await client.get(f"/v1/loans/{uuid.uuid4()}/report", headers=_auth_headers(raw_token))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "CC-404-LOAN"
