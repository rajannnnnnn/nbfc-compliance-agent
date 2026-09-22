"""POST /v1/loans (upsert by external_ref), GET /v1/loans/{id}. LLD §15.4."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.api.deps import get_tenant_id, get_tenant_session
from app.api.errors import APIError

router = APIRouter(prefix="/v1/loans", tags=["loans"])

_UPSERT_SQL = """
INSERT INTO loan_account
    (id, tenant_id, external_ref, product_type, is_microfinance, is_digital_lending,
     device_financed, sanctioned_at, disbursed_at, closed_at)
VALUES
    (:id, :tenant_id, :external_ref, :product_type, :is_microfinance, :is_digital_lending,
     :device_financed, :sanctioned_at, :disbursed_at, :closed_at)
ON CONFLICT (tenant_id, external_ref) DO UPDATE SET
    product_type = EXCLUDED.product_type,
    is_microfinance = EXCLUDED.is_microfinance,
    is_digital_lending = EXCLUDED.is_digital_lending,
    device_financed = EXCLUDED.device_financed,
    sanctioned_at = EXCLUDED.sanctioned_at,
    disbursed_at = EXCLUDED.disbursed_at,
    closed_at = EXCLUDED.closed_at
RETURNING id, (xmax = 0) AS inserted
"""

_GET_LOAN_SQL = """
SELECT la.id, la.external_ref, la.product_type, la.is_microfinance, la.is_digital_lending,
       la.device_financed, la.sanctioned_at, la.disbursed_at, la.closed_at,
       lcs.open_violations, lcs.open_ambiguous, lcs.open_no_clause, lcs.unresolved_conflicts,
       lcs.highest_severity, lcs.checks_run, lcs.last_assessed_at, lcs.state_version
FROM loan_account la
LEFT JOIN loan_compliance_state lcs ON lcs.loan_account_id = la.id
WHERE la.id = :id
"""


class LoanUpsert(BaseModel):
    external_ref: str
    product_type: str
    is_microfinance: bool = False
    is_digital_lending: bool = False
    device_financed: bool = False
    sanctioned_at: str | None = None
    disbursed_at: str | None = None
    closed_at: str | None = None


@router.post("")
async def upsert_loan(
    body: LoanUpsert,
    response: Response,
    tenant_id: UUID = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, Any]:
    loan_id = uuid7()
    row = (
        await session.execute(
            text(_UPSERT_SQL),
            {
                "id": str(loan_id),
                "tenant_id": str(tenant_id),
                "external_ref": body.external_ref,
                "product_type": body.product_type,
                "is_microfinance": body.is_microfinance,
                "is_digital_lending": body.is_digital_lending,
                "device_financed": body.device_financed,
                "sanctioned_at": body.sanctioned_at,
                "disbursed_at": body.disbursed_at,
                "closed_at": body.closed_at,
            },
        )
    ).first()
    await session.commit()
    assert row is not None
    response.status_code = 201 if row.inserted else 200
    return {"id": str(row.id), "external_ref": body.external_ref}


@router.get("/{loan_id}")
async def get_loan(
    loan_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, Any]:
    row = (await session.execute(text(_GET_LOAN_SQL), {"id": str(loan_id)})).first()
    if row is None:
        raise APIError("CC-404-LOAN", f"loan {loan_id} not found", detail={"loan_id": str(loan_id)})

    return {
        "loan_account": {
            "id": str(row.id),
            "external_ref": row.external_ref,
            "product_type": row.product_type,
            "is_microfinance": row.is_microfinance,
            "is_digital_lending": row.is_digital_lending,
            "device_financed": row.device_financed,
            "sanctioned_at": row.sanctioned_at.isoformat() if row.sanctioned_at else None,
            "disbursed_at": row.disbursed_at.isoformat() if row.disbursed_at else None,
            "closed_at": row.closed_at.isoformat() if row.closed_at else None,
        },
        "loan_compliance_state": (
            None
            if row.state_version is None
            else {
                "open_violations": row.open_violations,
                "open_ambiguous": row.open_ambiguous,
                "open_no_clause": row.open_no_clause,
                "unresolved_conflicts": row.unresolved_conflicts,
                "highest_severity": row.highest_severity,
                "checks_run": row.checks_run,
                "last_assessed_at": (
                    row.last_assessed_at.isoformat() if row.last_assessed_at else None
                ),
                "state_version": row.state_version,
            }
        ),
    }
