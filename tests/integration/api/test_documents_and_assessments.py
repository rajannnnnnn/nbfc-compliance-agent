"""End-to-end API flow: auth -> loan upsert -> document submit (sync extraction) ->
assessments retrieval. The LLM client is overridden via FastAPI's dependency_overrides
(app.api.deps.get_llm_client) so no real network call happens — the same seam every other
integration test in this codebase already relies on when it hands a stub `LLMClient` to
`assess_fact`/`extract_document` directly."""

import hashlib
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sqltext

from app.api.deps import get_llm_client, hash_token
from app.config import get_settings
from app.corpus.service import ingest
from app.db.engine import get_sessionmaker
from app.domain.verdicts import VerdictDraft
from app.llm.client import CallRecord, LLMClient
from app.main import app

pytestmark = pytest.mark.integration

KFS_TEXT = (
    "KEY FACTS STATEMENT\n"
    "The Annual Percentage Rate applicable to this loan is 18.5% p.a.\n"
    "Sanctioned amount: Rs 5,00,000.\n"
)


def _stub_client(settings) -> LLMClient:
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
        # extraction: every field absent — keeps the flow simple and deterministic.
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


async def test_no_bearer_token_is_401():
    async with await _client() as client:
        r = await client.get("/v1/loans/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "CC-401-AUTH"


async def test_full_flow_upsert_submit_assess_retrieve(active_snapshot, tenant):
    _tenant_id, raw_token = tenant
    async with await _client() as client:
        r = await client.post(
            "/v1/loans",
            json={"external_ref": "LN-API-1", "product_type": "personal"},
            headers=_auth_headers(raw_token),
        )
        assert r.status_code == 201
        loan_id = r.json()["id"]

        # Upsert again: same external_ref updates rather than duplicating (200, not 201).
        r2 = await client.post(
            "/v1/loans",
            json={"external_ref": "LN-API-1", "product_type": "personal"},
            headers=_auth_headers(raw_token),
        )
        assert r2.status_code == 200
        assert r2.json()["id"] == loan_id

        content = KFS_TEXT
        sha = hashlib.sha256(content.encode()).hexdigest()
        r3 = await client.post(
            f"/v1/loans/{loan_id}/documents",
            json={
                "event_date": "2026-04-01",
                "source_uri": "lms://test/doc1",
                "content_sha256": sha,
                "text": content,
                "is_synthetic": True,
                "assess": False,  # keep this test to the sync (extraction) half only
            },
            headers=_auth_headers(raw_token),
        )
        assert r3.status_code == 202
        document_id = r3.json()["document_id"]
        assert document_id

        # Duplicate submission (same content hash) is rejected.
        r4 = await client.post(
            f"/v1/loans/{loan_id}/documents",
            json={
                "event_date": "2026-04-01",
                "source_uri": "lms://test/doc1-again",
                "content_sha256": sha,
                "text": content,
                "assess": False,
            },
            headers=_auth_headers(raw_token),
        )
        assert r4.status_code == 409
        assert r4.json()["error"]["code"] == "CC-409-DUPLICATE-DOC"

        # Hash mismatch is rejected before anything is persisted.
        r5 = await client.post(
            f"/v1/loans/{loan_id}/documents",
            json={
                "event_date": "2026-04-01",
                "source_uri": "lms://test/doc2",
                "content_sha256": "0" * 64,
                "text": content,
                "assess": False,
            },
            headers=_auth_headers(raw_token),
        )
        assert r5.status_code == 400
        assert r5.json()["error"]["code"] == "CC-400-HASH-MISMATCH"

        r6 = await client.get(f"/v1/loans/{loan_id}/assessments", headers=_auth_headers(raw_token))
        assert r6.status_code == 200
        assert r6.json()["disclaimer"].startswith("Cited compliance findings")


async def test_idempotency_key_replays_same_response(active_snapshot, tenant):
    _tenant_id, raw_token = tenant
    async with await _client() as client:
        r = await client.post(
            "/v1/loans",
            json={"external_ref": "LN-API-2", "product_type": "personal"},
            headers=_auth_headers(raw_token),
        )
        loan_id = r.json()["id"]

        content = "CLOSURE STATEMENT\nLoan closed on 01/05/2026.\n"
        sha = hashlib.sha256(content.encode()).hexdigest()
        headers = {**_auth_headers(raw_token), "Idempotency-Key": "idem-key-1"}
        body = {
            "doc_type": "closure_statement",
            "event_date": "2026-05-01",
            "source_uri": "lms://test/closure",
            "content_sha256": sha,
            "text": content,
            "assess": False,
        }

        r1 = await client.post(f"/v1/loans/{loan_id}/documents", json=body, headers=headers)
        assert r1.status_code == 202

        r2 = await client.post(f"/v1/loans/{loan_id}/documents", json=body, headers=headers)
        assert r2.status_code == 202
        assert r2.json() == r1.json()

        bad_body = {**body, "source_uri": "lms://test/different"}
        r3 = await client.post(f"/v1/loans/{loan_id}/documents", json=bad_body, headers=headers)
        assert r3.status_code == 409
        assert r3.json()["error"]["code"] == "CC-409-IDEMPOTENCY"


async def test_get_loan_not_found_is_404_not_leaked(active_snapshot, tenant):
    _tenant_id, raw_token = tenant
    async with await _client() as client:
        r = await client.get(f"/v1/loans/{uuid.uuid4()}", headers=_auth_headers(raw_token))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "CC-404-LOAN"
