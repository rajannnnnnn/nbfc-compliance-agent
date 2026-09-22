from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class Citation(BaseModel):
    clause_path: str
    role: Literal["decisive", "supporting", "context_only"]
    quoted_clause_excerpt: str
    context_note: str | None = None


class VerdictDraft(BaseModel):
    """Exactly what the model is allowed to return. Nothing more — deliberately no `severity`
    field. The model cannot set severity (LLD §4)."""

    verdict: Literal["compliant", "violation", "ambiguous", "no_clause_found"]
    citations: list[Citation]
    rationale: str = Field(max_length=1200)
    confidence_band: Literal["high", "medium", "low"]


class StageTelemetry(BaseModel):
    """Not defined in LLD §4 despite being referenced by AssessmentResult — added here."""

    stage_a_ms: int | None = None
    stage_b_ms: int | None = None
    stage_c_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    model_id: str | None = None
    adapter_id: str | None = None
    prompt_version: str | None = None


class AssessmentResult(BaseModel):
    check_key: str
    field_key: str | None
    event_date: date
    verdict: str
    severity: str
    confidence_band: str
    rationale: str
    decided_by: Literal["rule", "model", "validator_downgrade", "shadow"]
    rule_id: str | None
    is_shadow: bool
    is_whatif: bool = False
    citations: list[Citation]
    telemetry: StageTelemetry
    corpus_snapshot_id: UUID
    candidate_clause_count: int = 0
