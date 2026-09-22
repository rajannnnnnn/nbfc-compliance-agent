from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class DocumentSubmission(BaseModel):
    tenant_id: UUID
    loan_account_id: UUID
    doc_type: str | None
    event_date: date
    source_uri: str
    content_sha256: str
    text: str
    is_synthetic: bool = True
    assess: bool = True


class ParsedDocument(BaseModel):
    text: str
    char_count: int
    page_count: int | None = None
    ocr_used: bool = False
    language: str = "en"


class LoanAccountRef(BaseModel):
    """The subset of loan_account a rule or retrieval call needs, passed in rather than
    fetched — keeps rules and retrieve/ free of a session dependency (LLD §1 dependency rule)."""

    id: UUID
    tenant_id: UUID
    external_ref: str
    product_type: str
    is_microfinance: bool
    is_digital_lending: bool
    device_financed: bool
    entity_type: str = "nbfc"


class DocumentRecord(BaseModel):
    id: UUID
    tenant_id: UUID
    loan_account_id: UUID
    doc_type: str
    event_date: date
    content_sha256: str
    char_count: int
    span_budget_chars: int
    span_used_chars: int
    submitted_at: datetime
