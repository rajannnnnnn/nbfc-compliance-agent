"""eval_case, eval_run, eval_result, audit_event

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE eval_case (
            id             uuid PRIMARY KEY,
            case_ref       text UNIQUE NOT NULL,
            suite          text NOT NULL,
            stage          text NOT NULL CHECK (stage IN ('extraction','retrieval','verdict','end_to_end')),
            doc_type       doc_type,
            input_ref      text NOT NULL,
            event_date     date NOT NULL,
            account_profile jsonb NOT NULL,
            expected       jsonb NOT NULL,
            tolerance      jsonb NOT NULL DEFAULT '{}',
            is_adversarial boolean NOT NULL DEFAULT false,
            notes          text
        )
        """
    )

    op.execute(
        """
        CREATE TABLE eval_run (
            id                 uuid PRIMARY KEY,
            started_at         timestamptz NOT NULL DEFAULT now(),
            finished_at        timestamptz,
            git_sha            text NOT NULL,
            corpus_snapshot_id uuid NOT NULL REFERENCES corpus_snapshot(id),
            model_config       jsonb NOT NULL,
            serving_mode       serving_mode NOT NULL,
            suite              text NOT NULL,
            case_count         int  NOT NULL,
            metrics            jsonb,
            cost_usd           numeric(10,6)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE eval_result (
            id           uuid PRIMARY KEY,
            eval_run_id  uuid NOT NULL REFERENCES eval_run(id) ON DELETE CASCADE,
            eval_case_id uuid NOT NULL REFERENCES eval_case(id),
            passed       boolean NOT NULL,
            actual       jsonb NOT NULL,
            diff         jsonb,
            latency_ms   int
        )
        """
    )

    op.execute(
        """
        CREATE TABLE audit_event (
            id          uuid PRIMARY KEY,
            tenant_id   uuid REFERENCES tenant(id),
            actor       text NOT NULL,
            action      text NOT NULL,
            entity_type text NOT NULL,
            entity_id   uuid,
            request_id  text,
            detail      jsonb NOT NULL DEFAULT '{}',
            created_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_audit_entity ON audit_event (entity_type, entity_id, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_event")
    op.execute("DROP TABLE IF EXISTS eval_result")
    op.execute("DROP TABLE IF EXISTS eval_run")
    op.execute("DROP TABLE IF EXISTS eval_case")
