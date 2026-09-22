"""Orchestration; the only public entry point. LLD §3.1.

Per ADR-017: runs synchronously inside the API request handler (not a Celery task) — document
text never crosses a queue boundary. Only `assess.document(document_id, ...)`, an id-only
payload, is queued afterwards by the caller.
"""

import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.config import Settings
from app.domain.facts import (
    BoolValue,
    DateTimeValue,
    DateValue,
    DaysValue,
    EnumValue,
    ExtractedFactIn,
    FactValue,
    IntValue,
    MoneyValue,
    RateValue,
    Span,
    StringValue,
    value_to_jsonable,
)
from app.extract.extractor import PROMPT_VERSION, extract_raw_fields
from app.extract.normalise import (
    NormalisationError,
    normalise_date,
    normalise_duration_days,
    normalise_money_to_paise,
    normalise_rate_to_bps,
    parse_full_datetime,
)
from app.extract.redact import redact
from app.extract.spans import admit_span, build_span
from app.llm.client import LLMClient
from app.obs.metrics import (
    facts_extracted_total,
    span_budget_exhausted_total,
    span_grounding_failures_total,
)
from app.schema.registry import FieldRegistry


class ExtractionError(Exception):
    pass


def _typed_value(value_type: str, value_raw: str) -> FactValue:
    if value_type == "date":
        return DateValue(v=normalise_date(value_raw))
    if value_type == "datetime":
        return DateTimeValue(v=parse_full_datetime(value_raw))
    if value_type == "money":
        return MoneyValue(paise=normalise_money_to_paise(value_raw))
    if value_type == "rate_bps":
        return RateValue(bps=normalise_rate_to_bps(value_raw))
    if value_type == "duration_days":
        return DaysValue(days=normalise_duration_days(value_raw))
    if value_type == "integer":
        return IntValue(v=int(value_raw))
    if value_type == "boolean":
        return BoolValue(v=value_raw.strip().lower() in ("true", "yes", "1"))
    if value_type == "enum":
        return EnumValue(v=value_raw.strip())
    return StringValue(v=value_raw)


async def extract_document(
    *,
    session: AsyncSession,
    document_id: UUID,
    tenant_id: UUID,
    loan_account_id: UUID,
    doc_type: str,
    document_text: str,
    client: LLMClient,
    registry: FieldRegistry,
    settings: Settings,
) -> list[UUID]:
    """Runs the full Stage A pipeline for one already-persisted `document` row and writes
    `extracted_fact` rows. Returns the ids of facts written."""
    raw = await extract_raw_fields(
        document_text=document_text,
        doc_type=doc_type,
        client=client,
        registry=registry,
        settings=settings,
    )

    extraction_run_id = uuid7()
    fact_ids: list[UUID] = []

    for field_key, extraction in raw.model_dump().items():
        spec = registry.get(field_key)
        is_absent = extraction["is_absent"]
        value_raw = extraction.get("value_raw")
        quoted_span_raw = extraction.get("quoted_span")
        confidence = extraction.get("confidence", 0.5)

        fact_id = uuid7()
        span_verified = False
        span_truncated = False
        redacted_raw: str | None = None
        redacted_quote: str | None = None
        typed_value: FactValue | None = None

        if not is_absent and value_raw:
            try:
                typed_value = _typed_value(spec.type, value_raw)
            except (NormalisationError, ValueError):
                # A value that fails to normalise is treated as absent rather than stored
                # wrong — a bad typed value would corrupt every downstream numeric rule.
                is_absent = True

        if typed_value is None:
            # Either value_raw was empty/falsy or normalisation failed above — either way
            # there is nothing to store as a value, so this is absent by construction. Never
            # leave is_absent=False with value_normalized=None: the DB CHECK constraint
            # forbids it, and a NULL "present" fact would be a silent data-integrity hole.
            is_absent = True

        if not is_absent and typed_value is not None:
            redacted_raw, _ = redact(value_raw, exempt=spec.redaction_exempt)

            if quoted_span_raw:
                span_obj: Span | None = build_span(
                    0, len(quoted_span_raw), quoted_span_raw, document_text
                )
                span_verified = span_obj.verified if span_obj else False
                if span_verified:
                    admitted, span_truncated = await admit_span(
                        session,
                        document_id=str(document_id),
                        span_len=len(quoted_span_raw),
                        settings=settings,
                    )
                    if admitted:
                        redacted_quote, _ = redact(quoted_span_raw, exempt=spec.redaction_exempt)
                    else:
                        span_verified = False  # budget exhausted; store the fact without evidence
                        span_budget_exhausted_total.labels(doc_type=doc_type).inc()
                else:
                    quoted_span_raw = None  # dropped — span-grounding check failed
                    span_grounding_failures_total.labels(doc_type=doc_type).inc()

        # Validates the shape before persistence — a value must be present iff not absent.
        ExtractedFactIn(
            field_key=field_key,
            value=None if is_absent else typed_value,
            value_raw=None if is_absent else redacted_raw,
            is_absent=is_absent,
            confidence=confidence,
            span=None,
        )

        await session.execute(
            text("""
                INSERT INTO extracted_fact
                    (id, tenant_id, document_id, loan_account_id, field_key, value_type,
                     value_raw, value_normalized, is_absent, confidence, quoted_span,
                     span_verified, span_truncated, extractor_model, prompt_version,
                     extraction_run_id)
                VALUES
                    (:id, :tenant_id, :document_id, :loan_account_id, :field_key, :value_type,
                     :value_raw, CAST(:value_normalized AS jsonb), :is_absent, :confidence,
                     :quoted_span, :span_verified, :span_truncated, :extractor_model,
                     :prompt_version, :extraction_run_id)
                """),
            {
                "id": str(fact_id),
                "tenant_id": str(tenant_id),
                "document_id": str(document_id),
                "loan_account_id": str(loan_account_id),
                "field_key": field_key,
                "value_type": None if is_absent else spec.type,
                "value_raw": None if is_absent else redacted_raw,
                "value_normalized": (
                    None if typed_value is None else json.dumps(value_to_jsonable(typed_value))
                ),
                "is_absent": is_absent,
                "confidence": confidence,
                "quoted_span": redacted_quote if not is_absent else None,
                "span_verified": span_verified,
                "span_truncated": span_truncated,
                "extractor_model": settings.extract_model,
                "prompt_version": PROMPT_VERSION,
                "extraction_run_id": str(extraction_run_id),
            },
        )
        if not is_absent:
            facts_extracted_total.labels(doc_type=doc_type, field_key=field_key).inc()
        fact_ids.append(fact_id)

    return fact_ids
