"""extensions and enums

Revision ID: 0001
Revises:
Create Date: 2026-09-19

"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

ENUMS: dict[str, list[str]] = {
    "entity_type": ["nbfc", "bank", "hfc", "ucb"],
    "lifecycle_stage": [
        "origination", "sanction", "disbursement", "servicing", "collections", "closure",
    ],
    "doc_type": [
        "kfs", "loan_agreement", "sanction_letter", "mitc", "call_transcript",
        "closure_statement", "noc", "docs_release_ack", "charge_satisfaction",
        "loan_application", "kyc_set", "income_proof", "bureau_report", "valuation_report",
        "field_investigation", "disbursement_memo", "payment_confirmation",
        "account_statement", "rate_reset_notice", "penal_charge_notice",
        "reminder_notice", "field_visit_report", "demand_notice", "settlement_letter",
        "possession_notice", "unknown",
    ],
    "value_type": [
        "date", "datetime", "time", "money", "rate_bps", "integer", "duration_days",
        "boolean", "enum", "string",
    ],
    "instrument_status": ["in_force", "notified_not_yet_effective", "draft", "superseded"],
    "verification_status": ["rbi_verified", "secondary_sourced", "unverified"],
    "chunk_kind": ["clause", "table_row", "illustration", "definition"],
    "verdict": ["compliant", "violation", "ambiguous", "no_clause_found"],
    "severity": ["critical", "major", "minor", "informational"],
    "confidence_band": ["high", "medium", "low"],
    "decided_by": ["rule", "model", "validator_downgrade", "shadow"],
    "citation_role": ["decisive", "supporting", "context_only"],
    "retrieval_source": ["pinned", "vector", "lexical", "reference_hop"],
    "conflict_type": ["value_mismatch", "date_order", "tolerance_breach", "missing_counterpart"],
    "job_status": ["queued", "running", "succeeded", "failed", "partial"],
    "serving_mode": ["hosted_baseline", "tuned_gpu", "on_prem"],
}


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, values in ENUMS.items():
        values_sql = ", ".join(f"'{v}'" for v in values)
        op.execute(f"CREATE TYPE {name} AS ENUM ({values_sql})")


def downgrade() -> None:
    for name in reversed(list(ENUMS)):
        op.execute(f"DROP TYPE IF EXISTS {name}")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS vector")
