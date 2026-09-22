"""GET /v1/loans/{id}/assessments. LLD §15.2.

`verification_status` on every citation is non-optional in the response (§15.2's own
sentence: "A consumer must be able to see that a citation rests on an instrument whose text
has not been confirmed against a regulator-hosted source") — resolved here by joining
`assessment_citation` back to `clause` and `regulation_instrument` rather than trusting
anything cached on the citation row itself.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_tenant_id, get_tenant_session
from app.api.errors import APIError
from app.verdict.report import assemble_report, report_to_json, report_to_pdf

router = APIRouter(prefix="/v1/loans", tags=["assessments"])

_SEVERITY_RANK = {"informational": 1, "minor": 2, "major": 3, "critical": 4}

_LOAN_SQL = "SELECT id, external_ref, product_type, is_microfinance, is_digital_lending FROM loan_account WHERE id = :id"

_ASSESSMENTS_SQL = """
SELECT id, check_key, field_key, event_date, verdict, severity, confidence_band, rationale,
       decided_by, rule_id, is_shadow, corpus_snapshot_id, stage_a_ms, stage_b_ms, stage_c_ms,
       cost_usd
FROM assessment
WHERE loan_account_id = :loan_id AND superseded_by_id IS NULL AND is_whatif = false
ORDER BY created_at DESC
"""

_CITATIONS_SQL = """
SELECT ac.assessment_id, ac.clause_path, ac.instrument_code, ac.role, ac.quoted_clause_excerpt,
       ac.context_note, c.effective_from, c.effective_to, ri.verification_status
FROM assessment_citation ac
JOIN clause c ON c.id = ac.clause_id
JOIN regulation_instrument ri ON ri.id = c.instrument_id
WHERE ac.assessment_id = ANY(:ids)
"""

_SNAPSHOT_SQL = "SELECT id, created_at FROM corpus_snapshot WHERE id = :id"


@router.get("/{loan_id}/assessments")
async def get_assessments(
    loan_id: UUID,
    verdict: str | None = Query(default=None),
    min_severity: str | None = Query(default=None),
    include_shadow: bool = Query(default=False),
    tenant_id: UUID = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, Any]:
    loan_row = (await session.execute(text(_LOAN_SQL), {"id": str(loan_id)})).first()
    if loan_row is None:
        raise APIError("CC-404-LOAN", f"loan {loan_id} not found", detail={"loan_id": str(loan_id)})

    rows = (await session.execute(text(_ASSESSMENTS_SQL), {"loan_id": str(loan_id)})).all()

    if not include_shadow:
        rows = [r for r in rows if not r.is_shadow]
    if verdict:
        rows = [r for r in rows if r.verdict == verdict]
    if min_severity:
        floor = _SEVERITY_RANK.get(min_severity, 0)
        rows = [r for r in rows if _SEVERITY_RANK.get(r.severity, 0) >= floor]

    citations_by_assessment: dict[UUID, list[dict[str, Any]]] = {r.id: [] for r in rows}
    if rows:
        cite_rows = (
            await session.execute(text(_CITATIONS_SQL), {"ids": [str(r.id) for r in rows]})
        ).all()
        for c in cite_rows:
            citations_by_assessment.setdefault(c.assessment_id, []).append(
                {
                    "clause_path": c.clause_path,
                    "instrument_code": c.instrument_code,
                    "role": c.role,
                    "effective_from": c.effective_from.isoformat() if c.effective_from else None,
                    "effective_to": c.effective_to.isoformat() if c.effective_to else None,
                    "verification_status": c.verification_status,
                    "context_note": c.context_note,
                    "quoted_clause_excerpt": c.quoted_clause_excerpt,
                }
            )

    assessments = [
        {
            "id": str(r.id),
            "check_key": r.check_key,
            "field_key": r.field_key,
            "event_date": r.event_date.isoformat(),
            "verdict": r.verdict,
            "severity": r.severity,
            "confidence_band": r.confidence_band,
            "decided_by": r.decided_by,
            "rule_id": r.rule_id,
            "is_shadow": r.is_shadow,
            "rationale": r.rationale,
            "citations": citations_by_assessment.get(r.id, []),
            "telemetry": {
                "stage_a_ms": r.stage_a_ms,
                "stage_b_ms": r.stage_b_ms,
                "stage_c_ms": r.stage_c_ms,
                "cost_usd": float(r.cost_usd) if r.cost_usd is not None else None,
            },
        }
        for r in rows
    ]

    snapshot_id = rows[0].corpus_snapshot_id if rows else None
    snapshot_created_at = None
    if snapshot_id is not None:
        snap_row = (await session.execute(text(_SNAPSHOT_SQL), {"id": str(snapshot_id)})).first()
        snapshot_created_at = snap_row.created_at.isoformat() if snap_row else None

    return {
        "loan_account": {
            "external_ref": loan_row.external_ref,
            "product_type": loan_row.product_type,
            "is_microfinance": loan_row.is_microfinance,
            "is_digital_lending": loan_row.is_digital_lending,
        },
        "corpus_snapshot": (
            {"id": str(snapshot_id), "created_at": snapshot_created_at} if snapshot_id else None
        ),
        "assessments": assessments,
        "disclaimer": "Cited compliance findings for internal review. Not legal advice.",
    }


@router.get("/{loan_id}/report")
async def get_report(
    loan_id: UUID,
    format: str = Query(default="json", pattern="^(json|pdf)$"),
    tenant_id: UUID = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_tenant_session),
) -> Any:
    report = await assemble_report(session, loan_id)
    if format == "pdf":
        pdf_bytes = report_to_pdf(report)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="clausecheck-{report.loan_external_ref}.pdf"'
            },
        )
    return report_to_json(report)
