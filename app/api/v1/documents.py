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

from fastapi import APIRouter, Depends, Form, Header, UploadFile
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
from app.extract.parse import ParseError, parse_document
from app.extract.service import extract_document
from app.llm.client import LLMClient
from app.obs.logging import get_logger
from app.schema.registry import FieldRegistry

logger = get_logger()

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
     source_uri, char_count, page_count, ocr_used, language, span_budget_chars, is_synthetic,
     classify_confidence)
VALUES
    (:id, :tid, :lid, :doc_type, :stage, :event_date, :sha, :source_uri, :char_count,
     :page_count, :ocr_used, :language, :span_budget, :is_synthetic, :classify_confidence)
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
    doc_type: str | None, text_: str, *, client: LLMClient, settings: Settings
) -> str:
    if doc_type:
        if doc_type not in DOC_TYPE_LIFECYCLE_STAGE:
            raise APIError(
                "CC-400-SCHEMA",
                f"unknown doc_type {doc_type!r}",
                detail={"doc_type": doc_type},
            )
        return doc_type

    result = await classify_document(text_, client=client, settings=settings)
    if result.doc_type == DocType.UNKNOWN.value:
        raise APIError(
            "CC-422-DOCTYPE-UNKNOWN",
            "classification below confidence floor; supply doc_type explicitly",
            detail={"confidence": result.confidence, "reason": result.reason},
        )
    return result.doc_type


async def _ingest_document(
    *,
    loan_id: UUID,
    tenant_id: UUID,
    session: AsyncSession,
    settings: Settings,
    client: LLMClient,
    request_id: str,
    route: str,
    request_hash: str,
    idempotency_key: str | None,
    doc_type_in: str | None,
    event_date_str: str,
    source_uri: str,
    content_sha256_in: str | None,
    document_text: str,
    is_synthetic: bool,
    assess: bool,
    page_count: int | None,
    ocr_used: bool,
    language: str,
) -> dict[str, Any]:
    """Shared by both submission routes (direct text and file upload) from the point where
    each has reduced its input down to plain extracted text — everything downstream
    (idempotency, dedup-by-hash, classification, extraction, queueing) is identical either
    way, so it lives once here rather than twice."""
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

    computed_hash = hashlib.sha256(document_text.encode("utf-8")).hexdigest()
    if content_sha256_in is not None and computed_hash != content_sha256_in:
        raise APIError("CC-400-HASH-MISMATCH", "content_sha256 does not match the supplied text")
    content_sha256 = computed_hash

    dup = (
        await session.execute(
            text(_EXISTING_DOC_SQL),
            {"tid": str(tenant_id), "lid": str(loan_id), "sha": content_sha256},
        )
    ).first()
    if dup is not None:
        raise APIError(
            "CC-409-DUPLICATE-DOC",
            "this document (by content hash) was already submitted for this account",
            detail={"existing_document_id": str(dup.id)},
        )

    try:
        event_date = date.fromisoformat(event_date_str)
    except ValueError as exc:
        raise APIError(
            "CC-400-SCHEMA", f"event_date {event_date_str!r} is not a valid ISO date"
        ) from exc

    doc_type = await _resolve_doc_type(doc_type_in, document_text, client=client, settings=settings)
    stage = DOC_TYPE_LIFECYCLE_STAGE[doc_type]

    document_id = uuid7()
    span_budget = int(len(document_text) * settings.span_budget_ratio)
    await session.execute(
        text(_INSERT_DOC_SQL),
        {
            "id": str(document_id),
            "tid": str(tenant_id),
            "lid": str(loan_id),
            "doc_type": doc_type,
            "stage": stage,
            "event_date": event_date,
            "sha": content_sha256,
            "source_uri": source_uri,
            "char_count": len(document_text),
            "page_count": page_count,
            "ocr_used": ocr_used,
            "language": language,
            "span_budget": span_budget,
            "is_synthetic": is_synthetic,
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
        document_text=document_text,
        client=client,
        registry=registry,
        settings=settings,
    )
    await session.commit()

    job_id = uuid7()
    if assess:
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
    return await _ingest_document(
        loan_id=loan_id,
        tenant_id=tenant_id,
        session=session,
        settings=settings,
        client=client,
        request_id=request_id,
        route=_route_key(loan_id),
        request_hash=request_hash,
        idempotency_key=idempotency_key,
        doc_type_in=body.doc_type,
        event_date_str=body.event_date,
        source_uri=body.source_uri,
        content_sha256_in=body.content_sha256,
        document_text=body.text,
        is_synthetic=body.is_synthetic,
        assess=body.assess,
        page_count=None,
        ocr_used=False,
        language="en",
    )


@router.post("/{loan_id}/documents/upload", status_code=202)
async def upload_document(
    loan_id: UUID,
    file: UploadFile,
    doc_type: str | None = Form(default=None),
    event_date: str = Form(...),
    source_uri: str | None = Form(default=None),
    is_synthetic: bool = Form(default=True),
    assess: bool = Form(default=True),
    tenant_id: UUID = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_tenant_session),
    settings: Settings = Depends(get_settings),
    client: LLMClient = Depends(get_llm_client),
    request_id: str = Depends(_get_request_id),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """Accepts a raw file (PDF, DOCX, TXT, or a scanned image) instead of pre-extracted
    text. Parsing (app/extract/parse.py) happens here, inside the request handler, for the
    same reason the text route's extraction does — ADR-017: document bytes never cross the
    Celery/Redis boundary. The bytes themselves live only in this function's local scope and
    are discarded the moment parsing returns (CLAUDE.md §2.3); only the parsed text and its
    hash are passed onward, identically to the direct-text route."""
    filename = file.filename or "upload"
    data = await file.read()

    if len(data) > settings.max_upload_bytes:
        raise APIError(
            "CC-413-PAYLOAD-TOO-LARGE",
            f"file exceeds the {settings.max_upload_bytes}-byte upload limit",
            detail={"filename": filename, "size_bytes": len(data)},
        )

    try:
        parsed = parse_document(filename=filename, data=data, settings=settings)
    except ParseError as exc:
        raise APIError("CC-422-PARSE-FAILED", str(exc), detail={"filename": filename}) from exc
    finally:
        del data

    logger.info(
        "document.upload_parsed",
        char_count=parsed.char_count,
        page_count=parsed.page_count,
        ocr_used=parsed.ocr_used,
    )

    request_hash = hashlib.sha256(
        json.dumps(
            {
                "filename": filename,
                "size": file.size,
                "doc_type": doc_type,
                "event_date": event_date,
                "source_uri": source_uri,
                "is_synthetic": is_synthetic,
                "assess": assess,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    return await _ingest_document(
        loan_id=loan_id,
        tenant_id=tenant_id,
        session=session,
        settings=settings,
        client=client,
        request_id=request_id,
        route=_route_key(loan_id) + "/upload",
        request_hash=request_hash,
        idempotency_key=idempotency_key,
        doc_type_in=doc_type,
        event_date_str=event_date,
        source_uri=source_uri or f"upload://{filename}",
        content_sha256_in=None,
        document_text=parsed.text,
        is_synthetic=is_synthetic,
        assess=assess,
        page_count=parsed.page_count,
        ocr_used=parsed.ocr_used,
        language=parsed.language,
    )
