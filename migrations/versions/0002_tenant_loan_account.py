"""tenant, loan_account

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant (
            id               uuid PRIMARY KEY,
            name             text        NOT NULL,
            entity_type      entity_type NOT NULL DEFAULT 'nbfc',
            retention_days   int         NOT NULL DEFAULT 180 CHECK (retention_days BETWEEN 30 AND 2555),
            is_active        boolean     NOT NULL DEFAULT true,
            created_at       timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE loan_account (
            id                 uuid PRIMARY KEY,
            tenant_id          uuid NOT NULL REFERENCES tenant(id),
            external_ref       text NOT NULL,
            product_type       text NOT NULL CHECK (product_type IN
                                  ('personal','microfinance','gold','vehicle','business',
                                   'consumer_durable','other')),
            is_microfinance    boolean NOT NULL DEFAULT false,
            is_digital_lending boolean NOT NULL DEFAULT false,
            device_financed    boolean NOT NULL DEFAULT false,
            sanctioned_at      date,
            disbursed_at       date,
            closed_at          date,
            created_at         timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, external_ref)
        )
        """
    )
    op.execute("CREATE INDEX ix_loan_tenant ON loan_account (tenant_id, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS loan_account")
    op.execute("DROP TABLE IF EXISTS tenant")
