"""`loan_compliance_state` recomputation. LLD §10.1 step 4 / M7-T03.

Per ADR-006, `is_shadow` (unverified clause basis) and `is_whatif` (a hypothetical `as_of`
override run, §15.4) are separate columns — this is what lets a shadow assessment still be
excluded from the account's real compliance picture while a what-if run is excluded from it
for an entirely different reason (it never happened; it's asking "what would today's rules
say"). Both are excluded here: neither should move the needle on what the tenant sees as the
account's current standing.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SEVERITY_RANK = {"critical": 4, "major": 3, "minor": 2, "informational": 1}

_OPEN_COUNTS_SQL = """
SELECT verdict, severity, COUNT(*) AS n
FROM assessment
WHERE tenant_id = :tenant_id AND loan_account_id = :loan_account_id
  AND superseded_by_id IS NULL AND is_shadow = false AND is_whatif = false
GROUP BY verdict, severity
"""

_CHECKS_RUN_SQL = """
SELECT COUNT(DISTINCT check_key) AS n
FROM assessment
WHERE tenant_id = :tenant_id AND loan_account_id = :loan_account_id
  AND superseded_by_id IS NULL AND is_whatif = false
"""

_UNRESOLVED_CONFLICTS_SQL = """
SELECT COUNT(*) AS n FROM fact_conflict
WHERE tenant_id = :tenant_id AND loan_account_id = :loan_account_id
  AND resolved_status = 'open'
"""

_UPSERT_SQL = """
INSERT INTO loan_compliance_state
    (loan_account_id, tenant_id, open_violations, open_ambiguous, open_no_clause,
     unresolved_conflicts, highest_severity, checks_run, last_assessed_at,
     corpus_snapshot_id, state_version)
VALUES
    (:loan_account_id, :tenant_id, :open_violations, :open_ambiguous, :open_no_clause,
     :unresolved_conflicts, :highest_severity, :checks_run, :last_assessed_at,
     :corpus_snapshot_id, 1)
ON CONFLICT (loan_account_id) DO UPDATE SET
    open_violations = EXCLUDED.open_violations,
    open_ambiguous = EXCLUDED.open_ambiguous,
    open_no_clause = EXCLUDED.open_no_clause,
    unresolved_conflicts = EXCLUDED.unresolved_conflicts,
    highest_severity = EXCLUDED.highest_severity,
    checks_run = EXCLUDED.checks_run,
    last_assessed_at = EXCLUDED.last_assessed_at,
    corpus_snapshot_id = EXCLUDED.corpus_snapshot_id,
    state_version = loan_compliance_state.state_version + 1
"""


async def recompute_loan_compliance_state(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    loan_account_id: UUID,
    corpus_snapshot_id: UUID,
) -> None:
    rows = await session.execute(
        text(_OPEN_COUNTS_SQL),
        {"tenant_id": str(tenant_id), "loan_account_id": str(loan_account_id)},
    )
    open_violations = open_ambiguous = open_no_clause = 0
    highest_severity: str | None = None
    for row in rows:
        if row.verdict == "violation":
            open_violations += row.n
        elif row.verdict == "ambiguous":
            open_ambiguous += row.n
        elif row.verdict == "no_clause_found":
            open_no_clause += row.n
        if _SEVERITY_RANK.get(row.severity, 0) > _SEVERITY_RANK.get(highest_severity or "", 0):
            highest_severity = row.severity

    checks_run = (
        await session.execute(
            text(_CHECKS_RUN_SQL),
            {"tenant_id": str(tenant_id), "loan_account_id": str(loan_account_id)},
        )
    ).scalar_one()

    unresolved_conflicts = (
        await session.execute(
            text(_UNRESOLVED_CONFLICTS_SQL),
            {"tenant_id": str(tenant_id), "loan_account_id": str(loan_account_id)},
        )
    ).scalar_one()

    await session.execute(
        text(_UPSERT_SQL),
        {
            "loan_account_id": str(loan_account_id),
            "tenant_id": str(tenant_id),
            "open_violations": open_violations,
            "open_ambiguous": open_ambiguous,
            "open_no_clause": open_no_clause,
            "unresolved_conflicts": unresolved_conflicts,
            "highest_severity": highest_severity,
            "checks_run": checks_run,
            "last_assessed_at": datetime.now(UTC),
            "corpus_snapshot_id": str(corpus_snapshot_id),
        },
    )
