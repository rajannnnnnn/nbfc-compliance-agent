"""SQLAlchemy ORM models. Mirrors the DDL in ClauseCheck_LLD_v1.0.md §3, with the fixes in
docs/DECISIONS.md applied: vector(1536) not 3072 (ADR-004), clause.applies_to_borrower_classes
(ADR-005), assessment.is_whatif (ADR-006)."""

from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    CHAR,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from uuid6 import uuid7

from app.config import get_settings
from app.db.base import Base, TimestampMixin

_settings = get_settings()


def _uuid() -> object:
    return uuid7()


def enum_col(name: str, *values: str, **kw):
    return mapped_column(PGEnum(*values, name=name, create_type=False), **kw)


# --- 3.2 Tenancy and accounts -------------------------------------------------------------


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenant"

    id: Mapped[object] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = enum_col(
        "entity_type", "nbfc", "bank", "hfc", "ucb", nullable=False, server_default="nbfc"
    )
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="180")
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=sa_text("true"))

    __table_args__ = (CheckConstraint("retention_days BETWEEN 30 AND 2555"),)


class LoanAccount(Base, TimestampMixin):
    __tablename__ = "loan_account"

    id: Mapped[object] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False
    )
    external_ref: Mapped[str] = mapped_column(Text, nullable=False)
    product_type: Mapped[str] = mapped_column(Text, nullable=False)
    is_microfinance: Mapped[bool] = mapped_column(nullable=False, server_default=sa_text("false"))
    is_digital_lending: Mapped[bool] = mapped_column(nullable=False, server_default=sa_text("false"))
    device_financed: Mapped[bool] = mapped_column(nullable=False, server_default=sa_text("false"))
    sanctioned_at: Mapped[date | None] = mapped_column(Date)
    disbursed_at: Mapped[date | None] = mapped_column(Date)
    closed_at: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        UniqueConstraint("tenant_id", "external_ref"),
        CheckConstraint(
            "product_type IN ('personal','microfinance','gold','vehicle','business',"
            "'consumer_durable','other')"
        ),
        Index("ix_loan_tenant", "tenant_id", "created_at"),
    )


# --- 3.3 Documents and facts ---------------------------------------------------------------


class Document(Base):
    __tablename__ = "document"

    id: Mapped[object] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False
    )
    loan_account_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("loan_account.id"), nullable=False
    )
    doc_type: Mapped[str] = enum_col(
        "doc_type",
        "kfs", "loan_agreement", "sanction_letter", "mitc", "call_transcript",
        "closure_statement", "noc", "docs_release_ack", "charge_satisfaction",
        "loan_application", "kyc_set", "income_proof", "bureau_report", "valuation_report",
        "field_investigation", "disbursement_memo", "payment_confirmation",
        "account_statement", "rate_reset_notice", "penal_charge_notice",
        "reminder_notice", "field_visit_report", "demand_notice", "settlement_letter",
        "possession_notice", "unknown",
        nullable=False,
    )
    lifecycle_stage: Mapped[str] = enum_col(
        "lifecycle_stage",
        "origination", "sanction", "disbursement", "servicing", "collections", "closure",
        nullable=False,
    )
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    content_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    source_uri: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    ocr_used: Mapped[bool] = mapped_column(nullable=False, server_default=sa_text("false"))
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default="en")
    is_synthetic: Mapped[bool] = mapped_column(nullable=False, server_default=sa_text("true"))
    redaction_profile: Mapped[str] = mapped_column(Text, nullable=False, server_default="v1")
    span_budget_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    span_used_chars: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    classify_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    extraction_version: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = enum_col(
        "job_status", "queued", "running", "succeeded", "failed", "partial",
        nullable=False, server_default="queued",
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("now()")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "loan_account_id", "content_sha256"),
        Index("ix_doc_account", "tenant_id", "loan_account_id", "event_date"),
    )


class ExtractedFact(Base, TimestampMixin):
    __tablename__ = "extracted_fact"

    id: Mapped[object] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False
    )
    document_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document.id", ondelete="CASCADE"), nullable=False
    )
    loan_account_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("loan_account.id"), nullable=False
    )
    field_key: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str | None] = enum_col(
        "value_type",
        "date", "datetime", "time", "money", "rate_bps", "integer", "duration_days",
        "boolean", "enum", "string",
    )
    value_raw: Mapped[str | None] = mapped_column(Text)
    value_normalized: Mapped[dict | None] = mapped_column(JSONB)
    is_absent: Mapped[bool] = mapped_column(nullable=False, server_default=sa_text("false"))
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    char_span_start: Mapped[int | None] = mapped_column(Integer)
    char_span_end: Mapped[int | None] = mapped_column(Integer)
    quoted_span: Mapped[str | None] = mapped_column(Text)
    span_verified: Mapped[bool] = mapped_column(nullable=False, server_default=sa_text("false"))
    span_truncated: Mapped[bool] = mapped_column(nullable=False, server_default=sa_text("false"))
    extractor_model: Mapped[str | None] = mapped_column(Text)
    extractor_adapter: Mapped[str | None] = mapped_column(Text)
    serving_mode: Mapped[str | None] = enum_col(
        "serving_mode", "hosted_baseline", "tuned_gpu", "on_prem"
    )
    prompt_version: Mapped[str | None] = mapped_column(Text)
    extraction_run_id: Mapped[object] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    __table_args__ = (
        Index("ix_fact_lookup", "tenant_id", "loan_account_id", "field_key"),
        Index("ix_fact_doc", "document_id"),
        CheckConstraint("is_absent OR value_normalized IS NOT NULL"),
        CheckConstraint("NOT is_absent OR (value_raw IS NULL AND quoted_span IS NULL)"),
    )


class FactConflict(Base):
    __tablename__ = "fact_conflict"

    id: Mapped[object] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False
    )
    loan_account_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("loan_account.id"), nullable=False
    )
    group_key: Mapped[str] = mapped_column(Text, nullable=False)
    field_key: Mapped[str] = mapped_column(Text, nullable=False)
    fact_a_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("extracted_fact.id", ondelete="CASCADE"), nullable=False
    )
    fact_b_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("extracted_fact.id", ondelete="CASCADE"), nullable=False
    )
    conflict_type: Mapped[str] = enum_col(
        "conflict_type", "value_mismatch", "date_order", "tolerance_breach",
        "missing_counterpart", nullable=False,
    )
    delta: Mapped[dict] = mapped_column(JSONB, nullable=False)
    operator: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("now()")
    )

    __table_args__ = (UniqueConstraint("tenant_id", "group_key", "fact_a_id", "fact_b_id"),)


# --- 3.4 Corpus ------------------------------------------------------------------------------


class CorpusSnapshot(Base):
    __tablename__ = "corpus_snapshot"

    id: Mapped[object] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("now()")
    )
    instrument_manifest: Mapped[dict] = mapped_column(JSONB, nullable=False)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_version: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=sa_text("false"))
    notes: Mapped[str | None] = mapped_column(Text)


class RegulationInstrument(Base):
    __tablename__ = "regulation_instrument"

    id: Mapped[object] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    snapshot_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("corpus_snapshot.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    official_title: Mapped[str] = mapped_column(Text, nullable=False)
    circular_number: Mapped[str | None] = mapped_column(Text)
    notification_id: Mapped[str | None] = mapped_column(Text)
    issued_on: Mapped[date | None] = mapped_column(Date)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = enum_col(
        "instrument_status", "in_force", "notified_not_yet_effective", "draft", "superseded",
        nullable=False,
    )
    applies_to_entity_types: Mapped[list[str]] = mapped_column(
        ARRAY(PGEnum("nbfc", "bank", "hfc", "ucb", name="entity_type", create_type=False)),
        nullable=False,
        server_default=sa_text("'{nbfc}'"),
    )
    citable: Mapped[bool] = mapped_column(nullable=False, server_default=sa_text("true"))
    verification_status: Mapped[str] = enum_col(
        "verification_status", "rbi_verified", "secondary_sourced", "unverified", nullable=False
    )
    verification_note: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    parser_version: Mapped[str] = mapped_column(Text, nullable=False)
    superseded_by_code: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("snapshot_id", "code"),)


class RegulationSupersession(Base):
    __tablename__ = "regulation_supersession"

    id: Mapped[object] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    snapshot_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("corpus_snapshot.id", ondelete="CASCADE"), nullable=False
    )
    superseding_instrument_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("regulation_instrument.id", ondelete="CASCADE"),
        nullable=False,
    )
    superseded_circular_number: Mapped[str] = mapped_column(Text, nullable=False)
    superseded_title: Mapped[str] = mapped_column(Text, nullable=False)
    superseded_on: Mapped[date] = mapped_column(Date, nullable=False)


class Clause(Base):
    __tablename__ = "clause"

    id: Mapped[object] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    snapshot_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("corpus_snapshot.id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("regulation_instrument.id", ondelete="CASCADE"),
        nullable=False,
    )
    instrument_code: Mapped[str] = mapped_column(Text, nullable=False)
    clause_path: Mapped[str] = mapped_column(Text, nullable=False)
    chapter: Mapped[str | None] = mapped_column(Text)
    chapter_title: Mapped[str | None] = mapped_column(Text)
    section_letter: Mapped[str | None] = mapped_column(Text)
    section_title: Mapped[str | None] = mapped_column(Text)
    para_number: Mapped[str] = mapped_column(Text, nullable=False)
    para_sort: Mapped[int] = mapped_column(Integer, nullable=False)
    level2_label: Mapped[str | None] = mapped_column(Text)
    level3_label: Mapped[str | None] = mapped_column(Text)
    heading: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_with_stem: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_kind: Mapped[str] = enum_col(
        "chunk_kind", "clause", "table_row", "illustration", "definition",
        nullable=False, server_default="clause",
    )
    chunk_strategy: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    citable: Mapped[bool] = mapped_column(nullable=False, server_default=sa_text("true"))
    # ADR-005: borrower-class scoping, absent from the LLD's DDL — the predicate that makes
    # the PRD §11 temporal pair (microfinance vs general) producible at all.
    applies_to_borrower_classes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=sa_text("'{}'")
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(_settings.embedding_dimension))
    # tsv is a generated column — created via raw DDL in the migration, mapped read-only here.
    tsv = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("snapshot_id", "clause_path"),)


class ClauseReference(Base):
    __tablename__ = "clause_reference"

    id: Mapped[object] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    snapshot_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("corpus_snapshot.id", ondelete="CASCADE"), nullable=False
    )
    from_clause_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("clause.id", ondelete="CASCADE"), nullable=False
    )
    to_instrument_code: Mapped[str] = mapped_column(Text, nullable=False)
    to_clause_path: Mapped[str | None] = mapped_column(Text)
    reference_text: Mapped[str] = mapped_column(Text, nullable=False)
    reference_kind: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "reference_kind IN ('incorporates','amends','repeals','see_also')"
        ),
        Index("ix_ref_from", "from_clause_id", "reference_kind"),
    )


# --- 3.5 Assessments -------------------------------------------------------------------------


class Assessment(Base):
    __tablename__ = "assessment"

    id: Mapped[object] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False
    )
    loan_account_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("loan_account.id"), nullable=False
    )
    document_id: Mapped[object | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document.id", ondelete="SET NULL")
    )
    check_key: Mapped[str] = mapped_column(Text, nullable=False)
    field_key: Mapped[str | None] = mapped_column(Text)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    verdict: Mapped[str] = enum_col(
        "verdict", "compliant", "violation", "ambiguous", "no_clause_found", nullable=False
    )
    severity: Mapped[str] = enum_col(
        "severity", "critical", "major", "minor", "informational", nullable=False
    )
    confidence_band: Mapped[str] = enum_col(
        "confidence_band", "high", "medium", "low", nullable=False
    )
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[str] = enum_col(
        "decided_by", "rule", "model", "validator_downgrade", "shadow", nullable=False
    )
    rule_id: Mapped[str | None] = mapped_column(Text)
    is_shadow: Mapped[bool] = mapped_column(nullable=False, server_default=sa_text("false"))
    # ADR-006: separate from is_shadow. A what-if `as_of` override run, not an unverified basis.
    is_whatif: Mapped[bool] = mapped_column(nullable=False, server_default=sa_text("false"))
    model_id: Mapped[str | None] = mapped_column(Text)
    adapter_id: Mapped[str | None] = mapped_column(Text)
    serving_mode: Mapped[str] = enum_col(
        "serving_mode", "hosted_baseline", "tuned_gpu", "on_prem", nullable=False
    )
    prompt_version: Mapped[str | None] = mapped_column(Text)
    corpus_snapshot_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("corpus_snapshot.id"), nullable=False
    )
    candidate_clause_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    stage_a_ms: Mapped[int | None] = mapped_column(Integer)
    stage_b_ms: Mapped[int | None] = mapped_column(Integer)
    stage_c_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6))
    request_id: Mapped[str] = mapped_column(Text, nullable=False)
    superseded_by_id: Mapped[object | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assessment.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("now()")
    )

    __table_args__ = (
        Index("ix_assess_account", "tenant_id", "loan_account_id", "created_at"),
        Index(
            "ix_assess_open",
            "tenant_id",
            "verdict",
            "severity",
            postgresql_where=sa_text("superseded_by_id IS NULL"),
        ),
    )


class AssessmentCitation(Base):
    __tablename__ = "assessment_citation"

    id: Mapped[object] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    assessment_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assessment.id", ondelete="CASCADE"), nullable=False
    )
    clause_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("clause.id"), nullable=False
    )
    clause_path: Mapped[str] = mapped_column(Text, nullable=False)
    instrument_code: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = enum_col(
        "citation_role", "decisive", "supporting", "context_only", nullable=False
    )
    retrieval_source: Mapped[str | None] = enum_col(
        "retrieval_source", "pinned", "vector", "lexical", "reference_hop"
    )
    rank: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[float | None] = mapped_column(Numeric(8, 5))
    quoted_clause_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    context_note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_cite_assess", "assessment_id", "role"),)


class LoanComplianceState(Base):
    __tablename__ = "loan_compliance_state"

    loan_account_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("loan_account.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False
    )
    open_violations: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    open_ambiguous: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    open_no_clause: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    unresolved_conflicts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    highest_severity: Mapped[str | None] = enum_col(
        "severity", "critical", "major", "minor", "informational"
    )
    checks_run: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    corpus_snapshot_id: Mapped[object | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("corpus_snapshot.id")
    )
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


# --- 3.6 Evaluation and audit ---------------------------------------------------------------


class EvalCase(Base):
    __tablename__ = "eval_case"

    id: Mapped[object] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    case_ref: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    suite: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    doc_type: Mapped[str | None] = enum_col(
        "doc_type",
        "kfs", "loan_agreement", "sanction_letter", "mitc", "call_transcript",
        "closure_statement", "noc", "docs_release_ack", "charge_satisfaction",
        "loan_application", "kyc_set", "income_proof", "bureau_report", "valuation_report",
        "field_investigation", "disbursement_memo", "payment_confirmation",
        "account_statement", "rate_reset_notice", "penal_charge_notice",
        "reminder_notice", "field_visit_report", "demand_notice", "settlement_letter",
        "possession_notice", "unknown",
    )
    input_ref: Mapped[str] = mapped_column(Text, nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    account_profile: Mapped[dict] = mapped_column(JSONB, nullable=False)
    expected: Mapped[dict] = mapped_column(JSONB, nullable=False)
    tolerance: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=sa_text("'{}'"))
    is_adversarial: Mapped[bool] = mapped_column(nullable=False, server_default=sa_text("false"))
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "stage IN ('extraction','retrieval','verdict','end_to_end')"
        ),
    )


class EvalRun(Base):
    __tablename__ = "eval_run"

    id: Mapped[object] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    git_sha: Mapped[str] = mapped_column(Text, nullable=False)
    corpus_snapshot_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("corpus_snapshot.id"), nullable=False
    )
    model_config_json: Mapped[dict] = mapped_column("model_config", JSONB, nullable=False)
    serving_mode: Mapped[str] = enum_col(
        "serving_mode", "hosted_baseline", "tuned_gpu", "on_prem", nullable=False
    )
    suite: Mapped[str] = mapped_column(Text, nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metrics: Mapped[dict | None] = mapped_column(JSONB)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6))


class EvalResult(Base):
    __tablename__ = "eval_result"

    id: Mapped[object] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    eval_run_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("eval_run.id", ondelete="CASCADE"), nullable=False
    )
    eval_case_id: Mapped[object] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("eval_case.id"), nullable=False
    )
    passed: Mapped[bool] = mapped_column(nullable=False)
    actual: Mapped[dict] = mapped_column(JSONB, nullable=False)
    diff: Mapped[dict | None] = mapped_column(JSONB)
    latency_ms: Mapped[int | None] = mapped_column(Integer)


class AuditEvent(Base):
    __tablename__ = "audit_event"

    id: Mapped[object] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[object | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenant.id")
    )
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[object | None] = mapped_column(PGUUID(as_uuid=True))
    request_id: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=sa_text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_text("now()")
    )

    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id", "created_at"),)
