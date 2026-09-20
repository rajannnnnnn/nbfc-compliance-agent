"""Verdict orchestration. LLD §10.1.

Rules run before any model call and a firing rule short-circuits it entirely — not only a
cost decision: it means every arithmetic/date-window obligation is decided exactly, every
time, independent of model version. `NOT_APPLICABLE` from every rule falls through to
retrieval + model. A shadow rule persists (`is_shadow=true`, `decided_by='shadow'`) but does
not suppress the model path for that field — LLD §11.2's shadow mode measures a rule's
behaviour without making it citable; it says nothing about whether the model should also be
asked, and M6-T01's own acceptance criteria require the model path to still run.
"""

import json
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.config import Settings
from app.domain.clauses import ClauseCandidate, ClauseCandidateSet
from app.domain.documents import LoanAccountRef
from app.domain.enums import BorrowerClass
from app.domain.facts import DaysValue, ExtractedFactOut, MoneyValue, RateValue
from app.domain.verdicts import AssessmentResult, StageTelemetry, VerdictDraft
from app.llm.client import LLMClient
from app.retrieve.service import retrieve_candidates
from app.rules.base import FactIndex, FactRecord, MissingFact, NotApplicable, Rule, RuleOutcome
from app.rules.registry import is_shadow, rules_for_field
from app.schema.registry import FieldRegistry
from app.verdict.severity import severity_for
from app.verdict.state import recompute_loan_compliance_state
from app.verdict.validator import RejectedCitation, validate

PROMPT_VERSION = "assess_fact.v2"
_PROMPT_PATH = "app/prompts/verdict/assess_fact.v2.md"

_FACT_INDEX_SQL = """
SELECT DISTINCT ON (field_key) field_key, value_type, value_normalized, is_absent
FROM extracted_fact
WHERE loan_account_id = :loan_account_id
ORDER BY field_key, created_at DESC
"""

_INSTRUMENT_VERIFICATION_SQL = """
SELECT code, verification_status FROM regulation_instrument WHERE snapshot_id = :snapshot_id
"""

_CLAUSE_REFS_SQL = """
SELECT id, clause_path, text FROM clause
WHERE snapshot_id = :snapshot_id AND clause_path = ANY(:paths)
"""

_PRIOR_OPEN_ASSESSMENT_SQL = """
SELECT id FROM assessment
WHERE loan_account_id = :loan_account_id AND check_key = :check_key
  AND superseded_by_id IS NULL AND is_whatif = false
ORDER BY created_at DESC LIMIT 1
"""


async def _load_fact_index(session: AsyncSession, *, loan_account_id: UUID) -> FactIndex:
    rows = await session.execute(text(_FACT_INDEX_SQL), {"loan_account_id": str(loan_account_id)})
    facts = {
        row.field_key: FactRecord(
            field_key=row.field_key,
            value_type=row.value_type,
            value_normalized=(
                json.loads(row.value_normalized)
                if isinstance(row.value_normalized, str)
                else row.value_normalized
            ),
            is_absent=row.is_absent,
        )
        for row in rows
    }
    return FactIndex(facts=facts)


async def _load_instrument_verification(
    session: AsyncSession, *, snapshot_id: UUID
) -> dict[str, str]:
    rows = await session.execute(
        text(_INSTRUMENT_VERIFICATION_SQL), {"snapshot_id": str(snapshot_id)}
    )
    return {row.code: row.verification_status for row in rows}


class ClauseRefRow:
    __slots__ = ("id", "text")

    def __init__(self, id: UUID, text: str):
        self.id = id
        self.text = text


async def _load_clause_refs(
    session: AsyncSession, *, snapshot_id: UUID, clause_paths: list[str]
) -> dict[str, ClauseRefRow]:
    """path -> (clause_id, text). Every persisted citation must resolve to a real `clause`
    row (CLAUDE.md §2.1) — this is the single lookup both the rule path and the model path
    use to attach a real `clause_id` before an `assessment_citation` row is ever written."""
    if not clause_paths:
        return {}
    rows = await session.execute(
        text(_CLAUSE_REFS_SQL), {"snapshot_id": str(snapshot_id), "paths": clause_paths}
    )
    return {row.clause_path: ClauseRefRow(id=row.id, text=row.text) for row in rows}


def _render_value_display(fact: ExtractedFactOut) -> str:
    if fact.is_absent or fact.value is None:
        return "(absent)"
    value = fact.value
    if isinstance(value, MoneyValue):
        return f"paise {value.paise}"
    if isinstance(value, RateValue):
        return f"{value.bps} bps"
    if isinstance(value, DaysValue):
        return f"{value.days} days"
    return str(value.v)


def _render_clause_block(candidates: list[ClauseCandidate]) -> str:
    if not candidates:
        return "(none)"
    lines = []
    for c in candidates:
        heading = f" — {c.heading}" if c.heading else ""
        lines.append(f"[{c.clause_path}]{heading}\n{c.text}")
    return "\n\n".join(lines)


def _render_context_block(candidates: list[ClauseCandidate]) -> str:
    if not candidates:
        return "(none)"
    lines = []
    for c in candidates:
        note = f" ({c.context_note})" if c.context_note else ""
        lines.append(f"[{c.clause_path}]{note}\n{c.text}")
    return "\n\n".join(lines)


def _render_prompt(
    *,
    template: str,
    field_label: str,
    field_key: str,
    value_display: str,
    doc_type: str,
    doc_event_date: date,
    quoted_span: str,
    event_date: date,
    account: LoanAccountRef,
    candidates: ClauseCandidateSet,
) -> str:
    return template.format(
        event_date=event_date.isoformat(),
        field_label=field_label,
        field_key=field_key,
        value_display=value_display,
        doc_type=doc_type,
        doc_event_date=doc_event_date.isoformat(),
        quoted_span=quoted_span,
        product_type=account.product_type,
        is_microfinance=account.is_microfinance,
        is_digital_lending=account.is_digital_lending,
        device_financed=account.device_financed,
        candidate_block=_render_clause_block(candidates.candidates),
        context_block=_render_context_block(candidates.context_only),
    )


def _from_rule_outcome(
    *,
    rule: Rule,
    outcome: RuleOutcome,
    check_key: str,
    field_key: str,
    event_date: date,
    shadow: bool,
    snapshot_id: UUID,
    corpus_snapshot_id: UUID,
) -> AssessmentResult:
    return AssessmentResult(
        check_key=check_key,
        field_key=field_key,
        event_date=event_date,
        verdict=outcome.verdict,
        severity=severity_for(rule_id=rule.id, lifecycle_stage=None, verdict=outcome.verdict),
        confidence_band="high",
        rationale=outcome.rationale,
        decided_by="shadow" if shadow else "rule",
        rule_id=rule.id,
        is_shadow=shadow,
        citations=outcome.citations,
        telemetry=StageTelemetry(),
        corpus_snapshot_id=corpus_snapshot_id,
        candidate_clause_count=len(outcome.citations),
    )


async def _persist(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    loan_account_id: UUID,
    document_id: UUID | None,
    result: AssessmentResult,
    clause_id_by_path: dict[str, UUID],
    is_whatif: bool,
    settings: Settings,
    request_id: str,
    rejected: list[RejectedCitation] | None = None,
) -> UUID:
    prior = await session.execute(
        text(_PRIOR_OPEN_ASSESSMENT_SQL),
        {"loan_account_id": str(loan_account_id), "check_key": result.check_key},
    )
    prior_row = prior.first()

    assessment_id = uuid7()
    await session.execute(
        text("""
            INSERT INTO assessment
                (id, tenant_id, loan_account_id, document_id, check_key, field_key, event_date,
                 verdict, severity, confidence_band, rationale, decided_by, rule_id, is_shadow,
                 is_whatif, model_id, adapter_id, serving_mode, prompt_version,
                 corpus_snapshot_id, candidate_clause_count, stage_a_ms, stage_b_ms, stage_c_ms,
                 tokens_in, tokens_out, cost_usd, request_id)
            VALUES
                (:id, :tenant_id, :loan_account_id, :document_id, :check_key, :field_key,
                 :event_date, :verdict, :severity, :confidence_band, :rationale, :decided_by,
                 :rule_id, :is_shadow, :is_whatif, :model_id, :adapter_id, :serving_mode,
                 :prompt_version, :corpus_snapshot_id, :candidate_clause_count, :stage_a_ms,
                 :stage_b_ms, :stage_c_ms, :tokens_in, :tokens_out, :cost_usd, :request_id)
            """),
        {
            "id": str(assessment_id),
            "tenant_id": str(tenant_id),
            "loan_account_id": str(loan_account_id),
            "document_id": str(document_id) if document_id else None,
            "check_key": result.check_key,
            "field_key": result.field_key,
            "event_date": result.event_date,
            "verdict": result.verdict,
            "severity": result.severity,
            "confidence_band": result.confidence_band,
            "rationale": result.rationale,
            "decided_by": result.decided_by,
            "rule_id": result.rule_id,
            "is_shadow": result.is_shadow,
            "is_whatif": is_whatif,
            "model_id": result.telemetry.model_id,
            "adapter_id": result.telemetry.adapter_id,
            "serving_mode": settings.serving_mode,
            "prompt_version": result.telemetry.prompt_version,
            "corpus_snapshot_id": str(result.corpus_snapshot_id),
            "candidate_clause_count": result.candidate_clause_count,
            "stage_a_ms": result.telemetry.stage_a_ms,
            "stage_b_ms": result.telemetry.stage_b_ms,
            "stage_c_ms": result.telemetry.stage_c_ms,
            "tokens_in": result.telemetry.tokens_in,
            "tokens_out": result.telemetry.tokens_out,
            "cost_usd": result.telemetry.cost_usd,
            "request_id": request_id,
        },
    )

    for citation in result.citations:
        clause_id = clause_id_by_path.get(citation.clause_path)
        if clause_id is None:
            # CLAUDE.md §2.1: no verdict without a citation that resolves to a real `clause`
            # row. If we get here the validator kept a path it should have rejected — a bug
            # in the validator, not something to paper over with a fabricated id.
            raise AssertionError(
                f"citation {citation.clause_path!r} survived validation but has no known "
                "clause_id — refusing to persist an unresolvable citation"
            )
        await session.execute(
            text("""
                INSERT INTO assessment_citation
                    (id, assessment_id, clause_id, clause_path, instrument_code, role,
                     retrieval_source, rank, score, quoted_clause_excerpt, context_note)
                VALUES
                    (:id, :assessment_id, :clause_id, :clause_path, :instrument_code, :role,
                     :retrieval_source, :rank, :score, :quoted_clause_excerpt, :context_note)
                """),
            {
                "id": str(uuid7()),
                "assessment_id": str(assessment_id),
                "clause_id": str(clause_id),
                "clause_path": citation.clause_path,
                "instrument_code": citation.clause_path.split("/", 1)[0],
                "role": citation.role,
                "retrieval_source": None,
                "rank": None,
                "score": None,
                "quoted_clause_excerpt": citation.quoted_clause_excerpt,
                "context_note": citation.context_note,
            },
        )

    for rej in rejected or []:
        await session.execute(
            text("""
                INSERT INTO audit_event (id, tenant_id, actor, action, entity_type, entity_id,
                                          request_id, detail)
                VALUES (:id, :tenant_id, 'system', 'citation_rejected', 'assessment', :entity_id,
                        :request_id, CAST(:detail AS jsonb))
                """),
            {
                "id": str(uuid7()),
                "tenant_id": str(tenant_id),
                "entity_id": str(assessment_id),
                "request_id": request_id,
                "detail": json.dumps(
                    {"reason": str(rej.reason), "clause_path": rej.citation.clause_path}
                ),
            },
        )

    if prior_row is not None and not is_whatif:
        await session.execute(
            text("UPDATE assessment SET superseded_by_id = :new_id WHERE id = :old_id"),
            {"new_id": str(assessment_id), "old_id": str(prior_row.id)},
        )

    return assessment_id


async def assess_fact(
    *,
    session: AsyncSession,
    fact: ExtractedFactOut,
    account: LoanAccountRef,
    document_event_date: date,
    snapshot_id: UUID,
    settings: Settings,
    registry: FieldRegistry,
    client: LLMClient,
    request_id: str,
    as_of: date | None = None,
) -> list[AssessmentResult]:
    """Assesses every check that consumes `fact.field_key`. Returns one AssessmentResult per
    rule that fired plus, if no rule decided the field, one model-decided result.

    `document_event_date` is the source document's own event date (`extracted_fact` carries
    no event date of its own — only `document` does — so the caller, which already holds the
    `DocumentRecord`, supplies it). `as_of` overrides it for a what-if re-assessment (§15.4);
    such a run is persisted with `is_whatif=True` and never supersedes the account's real
    history."""
    event_date = as_of or document_event_date
    is_whatif = as_of is not None

    spec = registry.get(fact.field_key)
    facts = await _load_fact_index(session, loan_account_id=fact.loan_account_id)
    instrument_verification = await _load_instrument_verification(session, snapshot_id=snapshot_id)

    results: list[AssessmentResult] = []
    any_rule_decided = False

    for rule in rules_for_field(fact.field_key):
        clause_refs = await _load_clause_refs(
            session, snapshot_id=snapshot_id, clause_paths=rule.clause_paths
        )
        clause_excerpts = {path: ref.text for path, ref in clause_refs.items()}
        try:
            outcome = rule.evaluate(
                facts, account, as_of=event_date, clause_excerpts=clause_excerpts
            )
        except MissingFact:
            continue
        if isinstance(outcome, NotApplicable):
            continue

        shadow = is_shadow(rule.id, instrument_verification=instrument_verification)
        if not shadow:
            # A shadow rule fired but is not citable (LLD §11.2): it is measured and
            # persisted, but per M6-T01's own acceptance criteria it must NOT suppress the
            # model path for this field — only a non-shadow (citable) firing short-circuits
            # the model call entirely.
            any_rule_decided = True
        result = _from_rule_outcome(
            rule=rule,
            outcome=outcome,
            check_key=rule.check_key,
            field_key=fact.field_key,
            event_date=event_date,
            shadow=shadow,
            snapshot_id=snapshot_id,
            corpus_snapshot_id=snapshot_id,
        )
        clause_id_by_path = {path: ref.id for path, ref in clause_refs.items()}
        await _persist(
            session,
            tenant_id=account.tenant_id,
            loan_account_id=fact.loan_account_id,
            document_id=fact.document_id,
            result=result,
            clause_id_by_path=clause_id_by_path,
            is_whatif=is_whatif,
            settings=settings,
            request_id=request_id,
        )
        results.append(result)

    if any_rule_decided:
        if not is_whatif:
            await recompute_loan_compliance_state(
                session,
                tenant_id=account.tenant_id,
                loan_account_id=fact.loan_account_id,
                corpus_snapshot_id=snapshot_id,
            )
        return results

    borrower_class = (
        BorrowerClass.MICROFINANCE if account.is_microfinance else BorrowerClass.GENERAL
    )
    value_summary = _render_value_display(fact)
    query_text = f"{spec.label}: {value_summary}"
    query_vectors = await client.embed(
        [query_text], model=settings.embedding_model, dimensions=settings.embedding_dimension
    )

    candidates = await retrieve_candidates(
        session=session,
        snapshot_id=snapshot_id,
        entity_type=account.entity_type,
        borrower_class=borrower_class,
        as_of=event_date,
        field_key=fact.field_key,
        value_summary=value_summary,
        field_label=spec.label,
        field_description=spec.description,
        query_vector=query_vectors[0],
        settings=settings,
    )

    with open(_PROMPT_PATH) as f:
        template = f.read()

    prompt = _render_prompt(
        template=template,
        field_label=spec.label,
        field_key=fact.field_key,
        value_display=value_summary,
        doc_type=spec.doc_types[0] if spec.doc_types else "unknown",
        doc_event_date=event_date,
        quoted_span=fact.span.quoted if fact.span else "",
        event_date=event_date,
        account=account,
        candidates=candidates,
    )

    draft, call_record = await client.structured(
        model_cls=VerdictDraft,
        model=settings.verdict_model,
        messages=[{"role": "user", "content": prompt}],
        stage="verdict",
    )
    assert isinstance(draft, VerdictDraft)

    validated = validate(draft, candidates, as_of=event_date)
    decided_by = "validator_downgrade" if validated.downgraded else "model"

    result = AssessmentResult(
        check_key=f"F:{fact.field_key}",
        field_key=fact.field_key,
        event_date=event_date,
        verdict=validated.verdict,
        severity=severity_for(
            rule_id=None, lifecycle_stage=spec.lifecycle_stage, verdict=validated.verdict
        ),
        confidence_band=draft.confidence_band,
        rationale=draft.rationale,
        decided_by=decided_by,
        rule_id=None,
        is_shadow=False,
        is_whatif=is_whatif,
        citations=validated.citations,
        telemetry=StageTelemetry(
            stage_b_ms=None,
            stage_c_ms=call_record.wall_clock_ms,
            tokens_in=call_record.tokens_in,
            tokens_out=call_record.tokens_out,
            cost_usd=call_record.cost_usd,
            model_id=call_record.model,
            adapter_id=call_record.adapter_id,
            prompt_version=PROMPT_VERSION,
        ),
        corpus_snapshot_id=snapshot_id,
        candidate_clause_count=len(candidates.candidates),
    )
    clause_id_by_path = {
        c.clause_path: c.clause_id for c in [*candidates.candidates, *candidates.context_only]
    }
    await _persist(
        session,
        tenant_id=account.tenant_id,
        loan_account_id=fact.loan_account_id,
        document_id=fact.document_id,
        result=result,
        clause_id_by_path=clause_id_by_path,
        is_whatif=is_whatif,
        settings=settings,
        request_id=request_id,
        rejected=validated.rejected,
    )
    results.append(result)
    if not is_whatif:
        await recompute_loan_compliance_state(
            session,
            tenant_id=account.tenant_id,
            loan_account_id=fact.loan_account_id,
            corpus_snapshot_id=snapshot_id,
        )
    return results
