"""tenant api key hash, idempotency_key table

Revision ID: 0009
Revises: 0008

LLD §15 says "Bearer token; tenant resolved from the token" and requires the
`Idempotency-Key` header to be "honoured on all POSTs, stored for 24 hours against the
request hash" — but neither a token column nor an idempotency table appears anywhere in the
LLD's own DDL (§3). Added here rather than guessed at silently; see docs/DECISIONS.md
ADR-030. The raw token is never stored — only its SHA-256, matching the pattern already used
for document/instrument content hashes elsewhere in this schema.
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant ADD COLUMN api_key_hash char(64) UNIQUE")
    op.execute(
        """
        CREATE TABLE idempotency_key (
            id             uuid PRIMARY KEY,
            tenant_id      uuid NOT NULL REFERENCES tenant(id),
            key            text NOT NULL,
            route          text NOT NULL,
            request_hash   char(64) NOT NULL,
            status_code    int,
            response_body  jsonb,
            created_at     timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, key, route)
        )
        """
    )
    op.execute("CREATE INDEX ix_idempotency_created ON idempotency_key (created_at)")
    op.execute("ALTER TABLE idempotency_key ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY p_tenant ON idempotency_key
            USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cc_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON idempotency_key TO cc_app;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS p_tenant ON idempotency_key")
    op.execute("DROP TABLE IF EXISTS idempotency_key")
    op.execute("ALTER TABLE tenant DROP COLUMN IF EXISTS api_key_hash")
