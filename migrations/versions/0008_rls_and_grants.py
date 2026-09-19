"""RLS policies and role grants

Revision ID: 0008
Revises: 0007

Grants moved here from bootstrap SQL, per ADR-008: `GRANT ... ON ALL TABLES IN SCHEMA public`
issued before Alembic has created any table grants nothing. `ALTER DEFAULT PRIVILEGES` is
added so any future migration's new tables inherit the same policy automatically.
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

RLS_TABLES = [
    "loan_account",
    "document",
    "extracted_fact",
    "fact_conflict",
    "assessment",
    "loan_compliance_state",
]


def upgrade() -> None:
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY p_tenant ON {table}
                USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
            """
        )

    op.execute("ALTER TABLE assessment_citation ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY p_tenant_cite ON assessment_citation
            USING (EXISTS (SELECT 1 FROM assessment a
                           WHERE a.id = assessment_id
                             AND a.tenant_id = current_setting('app.tenant_id', true)::uuid))
        """
    )

    # Grants — conditional on the role existing, so a bootstrap that hasn't created cc_app yet
    # (e.g. a bare `alembic upgrade head` against a fresh superuser-only database in CI) does
    # not fail the migration outright.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cc_app') THEN
                GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO cc_app;
                GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cc_app;
                GRANT DELETE ON document, extracted_fact TO cc_app;
                REVOKE UPDATE, DELETE ON audit_event FROM cc_app;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                    GRANT SELECT, INSERT, UPDATE ON TABLES TO cc_app;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                    GRANT USAGE, SELECT ON SEQUENCES TO cc_app;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cc_app') THEN
                REVOKE ALL ON ALL TABLES IN SCHEMA public FROM cc_app;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM cc_app;
            END IF;
        END
        $$;
        """
    )
    op.execute("DROP POLICY IF EXISTS p_tenant_cite ON assessment_citation")
    op.execute("ALTER TABLE assessment_citation DISABLE ROW LEVEL SECURITY")
    for table in reversed(RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS p_tenant ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
