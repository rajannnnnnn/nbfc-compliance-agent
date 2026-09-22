"""assessment, assessment_citation, loan_compliance_state

Revision ID: 0006
Revises: 0005

`is_whatif` is not in the LLD's own DDL — added per ADR-006 so a what-if `as_of` override run
can be excluded from compliance-state counts without overloading `is_shadow`, which means
something different (unverified clause basis).
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE assessment (
            id                     uuid PRIMARY KEY,
            tenant_id              uuid NOT NULL REFERENCES tenant(id),
            loan_account_id        uuid NOT NULL REFERENCES loan_account(id),
            document_id            uuid REFERENCES document(id) ON DELETE SET NULL,
            check_key              text NOT NULL,
            field_key              text,
            event_date             date NOT NULL,
            verdict                verdict  NOT NULL,
            severity               severity NOT NULL,
            confidence_band        confidence_band NOT NULL,
            rationale              text NOT NULL,
            decided_by             decided_by NOT NULL,
            rule_id                text,
            is_shadow              boolean NOT NULL DEFAULT false,
            is_whatif              boolean NOT NULL DEFAULT false,
            model_id               text,
            adapter_id             text,
            serving_mode           serving_mode NOT NULL,
            prompt_version         text,
            corpus_snapshot_id     uuid NOT NULL REFERENCES corpus_snapshot(id),
            candidate_clause_count int  NOT NULL DEFAULT 0,
            stage_a_ms             int,
            stage_b_ms             int,
            stage_c_ms             int,
            tokens_in              int,
            tokens_out             int,
            cost_usd               numeric(10,6),
            request_id             text NOT NULL,
            superseded_by_id       uuid REFERENCES assessment(id),
            created_at             timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_assess_account ON assessment (tenant_id, loan_account_id, created_at DESC)")
    op.execute(
        "CREATE INDEX ix_assess_open ON assessment (tenant_id, verdict, severity) "
        "WHERE superseded_by_id IS NULL"
    )

    op.execute(
        """
        CREATE TABLE assessment_citation (
            id                     uuid PRIMARY KEY,
            assessment_id          uuid NOT NULL REFERENCES assessment(id) ON DELETE CASCADE,
            clause_id              uuid NOT NULL REFERENCES clause(id),
            clause_path            text NOT NULL,
            instrument_code        text NOT NULL,
            role                   citation_role NOT NULL,
            retrieval_source       retrieval_source,
            rank                   int,
            score                  numeric(8,5),
            quoted_clause_excerpt  text NOT NULL,
            context_note           text
        )
        """
    )
    op.execute("CREATE INDEX ix_cite_assess ON assessment_citation (assessment_id, role)")

    op.execute(
        """
        CREATE TABLE loan_compliance_state (
            loan_account_id      uuid PRIMARY KEY REFERENCES loan_account(id) ON DELETE CASCADE,
            tenant_id            uuid NOT NULL REFERENCES tenant(id),
            open_violations      int  NOT NULL DEFAULT 0,
            open_ambiguous       int  NOT NULL DEFAULT 0,
            open_no_clause       int  NOT NULL DEFAULT 0,
            unresolved_conflicts int  NOT NULL DEFAULT 0,
            highest_severity     severity,
            checks_run           int  NOT NULL DEFAULT 0,
            last_assessed_at     timestamptz,
            corpus_snapshot_id   uuid REFERENCES corpus_snapshot(id),
            state_version        int  NOT NULL DEFAULT 1
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS loan_compliance_state")
    op.execute("DROP TABLE IF EXISTS assessment_citation")
    op.execute("DROP TABLE IF EXISTS assessment")
