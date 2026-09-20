"""Account-level report assembly. LLD §6.6 module list, §15.4 `GET /v1/loans/{id}/report`.

Both `format=json` and `format=pdf` render the same `ReportData`: the synthetic-data
banner (CLAUDE.md §2.4 — a visible banner whenever any underlying document is
synthetic), the not-legal-advice disclaimer (PRD §6.3), and, per finding, the clause
path, instrument, effective window and `verification_status` — the same guarantee
`GET /v1/loans/{id}/assessments` makes, because a report is that endpoint's payload
reshaped for a human reader, not a separate source of truth.
"""

import io
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import APIError

DISCLAIMER = (
    "Cited compliance findings for internal review. Not legal advice. ClauseCheck does "
    "not determine legality; it reports which RBI clauses govern a fact and whether the "
    "extracted value satisfies them."
)
SYNTHETIC_BANNER = (
    "SYNTHETIC DATA: one or more documents underlying this report are synthetic test "
    "fixtures, not real borrower records."
)

_LOAN_SQL = (
    "SELECT id, external_ref, product_type, is_microfinance, is_digital_lending "
    "FROM loan_account WHERE id = :id"
)

_ASSESSMENTS_SQL = """
SELECT id, check_key, field_key, event_date, verdict, severity, confidence_band, rationale
FROM assessment
WHERE loan_account_id = :loan_id AND superseded_by_id IS NULL AND is_whatif = false
      AND is_shadow = false
ORDER BY severity DESC, event_date DESC
"""

_CITATIONS_SQL = """
SELECT ac.assessment_id, ac.clause_path, ac.instrument_code, ac.role,
       ri.official_title, c.effective_from, c.effective_to, ri.verification_status
FROM assessment_citation ac
JOIN clause c ON c.id = ac.clause_id
JOIN regulation_instrument ri ON ri.id = c.instrument_id
WHERE ac.assessment_id = ANY(:ids)
"""

_SYNTHETIC_SQL = (
    "SELECT bool_or(is_synthetic) AS any_synthetic FROM document WHERE loan_account_id = :id"
)


@dataclass
class ReportCitation:
    clause_path: str
    instrument_code: str
    official_title: str
    effective_from: str | None
    effective_to: str | None
    verification_status: str
    role: str


@dataclass
class ReportFinding:
    check_key: str
    field_key: str
    event_date: str
    verdict: str
    severity: str
    confidence_band: str
    rationale: str
    citations: list[ReportCitation] = field(default_factory=list)


@dataclass
class ReportData:
    loan_external_ref: str
    product_type: str
    is_microfinance: bool
    is_digital_lending: bool
    is_synthetic: bool
    disclaimer: str
    findings: list[ReportFinding] = field(default_factory=list)


async def assemble_report(session: AsyncSession, loan_id: UUID) -> ReportData:
    loan_row = (await session.execute(text(_LOAN_SQL), {"id": str(loan_id)})).first()
    if loan_row is None:
        raise APIError("CC-404-LOAN", f"loan {loan_id} not found", detail={"loan_id": str(loan_id)})

    is_synthetic = bool(
        (await session.execute(text(_SYNTHETIC_SQL), {"id": str(loan_id)})).scalar_one_or_none()
    )

    rows = (await session.execute(text(_ASSESSMENTS_SQL), {"loan_id": str(loan_id)})).all()
    citations_by_assessment: dict[Any, list[ReportCitation]] = {r.id: [] for r in rows}
    if rows:
        cite_rows = (
            await session.execute(text(_CITATIONS_SQL), {"ids": [str(r.id) for r in rows]})
        ).all()
        for c in cite_rows:
            citations_by_assessment.setdefault(c.assessment_id, []).append(
                ReportCitation(
                    clause_path=c.clause_path,
                    instrument_code=c.instrument_code,
                    official_title=c.official_title,
                    effective_from=c.effective_from.isoformat() if c.effective_from else None,
                    effective_to=c.effective_to.isoformat() if c.effective_to else None,
                    verification_status=c.verification_status,
                    role=c.role,
                )
            )

    findings = [
        ReportFinding(
            check_key=r.check_key,
            field_key=r.field_key,
            event_date=r.event_date.isoformat(),
            verdict=r.verdict,
            severity=r.severity,
            confidence_band=r.confidence_band,
            rationale=r.rationale,
            citations=citations_by_assessment.get(r.id, []),
        )
        for r in rows
    ]

    return ReportData(
        loan_external_ref=loan_row.external_ref,
        product_type=loan_row.product_type,
        is_microfinance=loan_row.is_microfinance,
        is_digital_lending=loan_row.is_digital_lending,
        is_synthetic=is_synthetic,
        disclaimer=DISCLAIMER,
        findings=findings,
    )


def report_to_json(report: ReportData) -> dict[str, Any]:
    body: dict[str, Any] = {
        "loan_account": {
            "external_ref": report.loan_external_ref,
            "product_type": report.product_type,
            "is_microfinance": report.is_microfinance,
            "is_digital_lending": report.is_digital_lending,
        },
        "disclaimer": report.disclaimer,
        "findings": [
            {
                "check_key": f.check_key,
                "field_key": f.field_key,
                "event_date": f.event_date,
                "verdict": f.verdict,
                "severity": f.severity,
                "confidence_band": f.confidence_band,
                "rationale": f.rationale,
                "citations": [
                    {
                        "clause_path": c.clause_path,
                        "instrument_code": c.instrument_code,
                        "official_title": c.official_title,
                        "effective_from": c.effective_from,
                        "effective_to": c.effective_to,
                        "verification_status": c.verification_status,
                        "role": c.role,
                    }
                    for c in f.citations
                ],
            }
            for f in report.findings
        ],
    }
    if report.is_synthetic:
        body["synthetic_data_banner"] = SYNTHETIC_BANNER
    return body


def report_to_pdf(report: ReportData) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, title=f"ClauseCheck report — {report.loan_external_ref}"
    )
    styles = getSampleStyleSheet()
    story: list[Any] = [
        Paragraph(f"ClauseCheck report — {report.loan_external_ref}", styles["Title"])
    ]

    if report.is_synthetic:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(SYNTHETIC_BANNER, styles["Heading3"]))

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(report.disclaimer, styles["Italic"]))
    story.append(Spacer(1, 6 * mm))

    for f in report.findings:
        story.append(
            Paragraph(
                f"{f.check_key} — {f.verdict.upper()} ({f.severity}, event {f.event_date})",
                styles["Heading2"],
            )
        )
        story.append(Paragraph(f.rationale, styles["Normal"]))
        if f.citations:
            table_rows = [["Clause", "Instrument", "Effective window", "Verification", "Role"]]
            for c in f.citations:
                window = f"{c.effective_from or '—'} to {c.effective_to or 'open'}"
                table_rows.append(
                    [c.clause_path, c.instrument_code, window, c.verification_status, c.role]
                )
            t = Table(table_rows, hAlign="LEFT")
            t.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, "grey"),
                        ("BACKGROUND", (0, 0), (-1, 0), "lightgrey"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ]
                )
            )
            story.append(Spacer(1, 2 * mm))
            story.append(t)
        story.append(Spacer(1, 6 * mm))

    if not report.findings:
        story.append(Paragraph("No findings recorded for this account.", styles["Normal"]))

    doc.build(story)
    return buf.getvalue()
