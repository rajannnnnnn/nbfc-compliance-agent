"""POST /v1/loans/{loan_id}/documents. LLD §15.1.

Per ADR-017: extraction runs synchronously inside this request handler — document text never
crosses the Celery/Redis boundary (CLAUDE.md §2.3). Only `assess.document(document_id, ...)`,
an id-only payload, is queued afterward.
"""

import hashlib
import json
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.api.deps import get_llm_client, get_tenant_id, get_tenant_session
from app.api.deps import get_request_id as _get_request_id
from app.api.errors import APIError
from app.config import Settings, get_settings
from app.domain.enums import DocType
from app.extract.classify import classify_document
from app.extract.service import extract_document
from app.llm.client import LLMClient
from app.schema.registry import FieldRegistry

router = APIRouter(prefix="/v1/loans", tags=["documents"])

# LLD §5's field registry is keyed by field, not by document. Lifecycle stage is a
# document-level property the LLD never derives anywhere; this mapping is the judgment call
# ADR-032 documents — chosen to match the stage every field belonging to that doc_type is
# overwhelmingly drawn from in fields.yaml, e.g. `kfs` fields are almost entirely `sanction`.
DOC_TYPE_LIFECYCLE_STAGE: dict[str, str] = {
    "kfs": "sanction",
    "loan_agreement": "sanction",
    "sanction_letter": "sanction",
    "mitc": "sanction",
    "loan_application": "origination",
    "kyc_set": "origination",
    "income_proof": "origination",
    "bureau_report": "origination",
    "valuation_report": "origination",
    "field_investigation": "origination",
    "disbursement_memo": "disbursement",
    "payment_confirmation": "disbursement",
    "account_statement": "servicing",
    "rate_reset_notice": "servicing",
    "call_transcript": "collections",
    "penal_charge_notice": "collections",
    "reminder_notice": "collections",
    "field_visit_report": "collections",
    "demand_notice": "collections",
    "settlement_letter": "collections",
    "possession_notice": "collections",
    "closure_statement": "closure",
    "noc": "closure",
    "docs_release_ack": "closure",
    "charge_satisfaction": "closure",
    "unknown": "origination",
}

_LOAN_TENANT_CHECK_SQL = "SELECT 1 FROM loan_account WHERE id = :id"

_EXISTING_DOC_SQL = """
SELECT id FROM document WHERE tenant_id = :tid AND loan_account_id = :lid
  AND content_sha256 = :sha
"""

_INSERT_DOC_SQL = """
INSERT INTO document
    (id, tenant_id, loan_account_id, doc_type, lifecycle_stage, event_date, content_sha256,
     source_uri, char_count, span_budget_chars, is_synthetic, classify_confidence)
VALUES
    (:id, :tid, :lid, :doc_type, :stage, :event_date, :sha, :source_uri, :char_count,
     :span_budget, :is_synthetic, :classify_confidence)
"""

_IDEMPOTENCY_LOOKUP_SQL = """
SELECT request_hash, status_code, response_body FROM idempotency_key
WHERE tenant_id = :tid AND key = :key AND route = :route
"""

_IDEMPOTENCY_INSERT_SQL = """
INSERT INTO idempotency_key (id, tenant_id, key, route, request_hash, status_code, response_body)
VALUES (:id, :tid, :key, :route, :hash, :status_code, CAST(:body AS jsonb))
"""


class DocumentSubmitRequest(BaseModel):
    doc_type: str | None = None
    event_date: str
    source_uri: str
    content_sha256: str
    text: str
    is_synthetic: bool = True
    assess: bool = True


def _route_key(loan_id: UUID) -> str:
    return f"POST /v1/loans/{loan_id}/documents"


async def _resolve_doc_type(
    body: DocumentSubmitRequest, *, client: LLMClient, settings: Settings
) -> str:
    if body.doc_type:
        if body.doc_type not in DOC_TYPE_LIFECYCLE_STAGE:
            raise APIError(
                "CC-400-SCHEMA",
                f"unknown doc_type {body.doc_type!r}",
                detail={"doc_type": body.doc_type},
            )
        return body.doc_type

    result = await classify_document(body.text, client=client, settings=settings)
    if result.doc_type == DocType.UNKNOWN.value:
        raise APIError(
            "CC-422-DOCTYPE-UNKNOWN",
            "classification below confidence floor; supply doc_type explicitly",
            detail={"confidence": result.confidence, "reason": result.reason},
        )
    return result.doc_type


@router.post("/{loan_id}/documents", status_code=202)
async def submit_document(
    loan_id: UUID,
    body: DocumentSubmitRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_tenant_session),
    settings: Settings = Depends(get_settings),
    client: LLMClient = Depends(get_llm_client),
    request_id: str = Depends(_get_request_id),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    request_hash = hashlib.sha256(body.model_dump_json().encode("utf-8")).hexdigest()
    route = _route_key(loan_id)

    if idempotency_key:
        existing = (
            await session.execute(
                text(_IDEMPOTENCY_LOOKUP_SQL),
                {"tid": str(tenant_id), "key": idempotency_key, "route": route},
            )
        ).first()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise APIError(
                    "CC-409-IDEMPOTENCY", "Idempotency-Key reused with a different request body"
                )
            stored = existing.response_body
            parsed: dict[str, Any] = json.loads(stored) if isinstance(stored, str) else stored
            return parsed

    loan_row = (await session.execute(text(_LOAN_TENANT_CHECK_SQL), {"id": str(loan_id)})).first()
    if loan_row is None:
        raise APIError("CC-404-LOAN", f"loan {loan_id} not found", detail={"loan_id": str(loan_id)})

    computed_hash = hashlib.sha256(body.text.encode("utf-8")).hexdigest()
    if computed_hash != body.content_sha256:
        raise APIError("CC-400-HASH-MISMATCH", "content_sha256 does not match the supplied text")

    dup = (
        await session.execute(
            text(_EXISTING_DOC_SQL),
            {"tid": str(tenant_id), "lid": str(loan_id), "sha": body.content_sha256},
        )
    ).first()
    if dup is not None:
        raise APIError(
            "CC-409-DUPLICATE-DOC",
            "this document (by content hash) was already submitted for this account",
            detail={"existing_document_id": str(dup.id)},
        )

    try:
        event_date = date.fromisoformat(body.event_date)
    except ValueError as exc:
        raise APIError(
            "CC-400-SCHEMA", f"event_date {body.event_date!r} is not a valid ISO date"
        ) from exc

    doc_type = await _resolve_doc_type(body, client=client, settings=settings)
    stage = DOC_TYPE_LIFECYCLE_STAGE[doc_type]

    document_id = uuid7()
    span_budget = int(len(body.text) * settings.span_budget_ratio)
    await session.execute(
        text(_INSERT_DOC_SQL),
        {
            "id": str(document_id),
            "tid": str(tenant_id),
            "lid": str(loan_id),
            "doc_type": doc_type,
            "stage": stage,
            "event_date": event_date,
            "sha": body.content_sha256,
            "source_uri": body.source_uri,
            "char_count": len(body.text),
            "span_budget": span_budget,
            "is_synthetic": body.is_synthetic,
            "classify_confidence": None,
        },
    )

    registry = FieldRegistry("app/schema/fields.yaml")
    await extract_document(
        session=session,
        document_id=document_id,
        tenant_id=tenant_id,
        loan_account_id=loan_id,
        doc_type=doc_type,
        document_text=body.text,
        client=client,
        registry=registry,
        settings=settings,
    )
    await session.commit()

    job_id = uuid7()
    if body.assess:
        from app.tasks.assess_tasks import assess_document

        assess_document.delay(str(document_id), str(tenant_id), request_id)

    response_body = {
        "document_id": str(document_id),
        "job_id": str(job_id),
        "status": "queued",
        "request_id": request_id,
    }

    if idempotency_key:
        await session.execute(
            text(_IDEMPOTENCY_INSERT_SQL),
            {
                "id": str(uuid7()),
                "tid": str(tenant_id),
                "key": idempotency_key,
                "route": route,
                "hash": request_hash,
                "status_code": 202,
                "body": json.dumps(response_body),
            },
        )
        await session.commit()

    return response_body
