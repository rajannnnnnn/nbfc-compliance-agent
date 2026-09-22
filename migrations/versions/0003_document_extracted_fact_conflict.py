"""document, extracted_fact, fact_conflict

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE document (
            id                 uuid PRIMARY KEY,
            tenant_id          uuid NOT NULL REFERENCES tenant(id),
            loan_account_id    uuid NOT NULL REFERENCES loan_account(id),
            doc_type           doc_type        NOT NULL,
            lifecycle_stage    lifecycle_stage NOT NULL,
            event_date         date            NOT NULL,
            content_sha256     char(64)        NOT NULL,
            source_uri         text            NOT NULL,
            char_count         int             NOT NULL,
            page_count         int,
            ocr_used           boolean         NOT NULL DEFAULT false,
            language           text            NOT NULL DEFAULT 'en',
            is_synthetic       boolean         NOT NULL DEFAULT true,
            redaction_profile  text            NOT NULL DEFAULT 'v1',
            span_budget_chars  int             NOT NULL,
            span_used_chars    int             NOT NULL DEFAULT 0,
            classify_confidence numeric(4,3),
            extraction_version text,
            status             job_status      NOT NULL DEFAULT 'queued',
            submitted_at       timestamptz     NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, loan_account_id, content_sha256)
        )
        """
    )
    op.execute("CREATE INDEX ix_doc_account ON document (tenant_id, loan_account_id, event_date)")

    op.execute(
        """
        CREATE TABLE extracted_fact (
            id                 uuid PRIMARY KEY,
            tenant_id          uuid NOT NULL REFERENCES tenant(id),
            document_id        uuid NOT NULL REFERENCES document(id) ON DELETE CASCADE,
            loan_account_id    uuid NOT NULL REFERENCES loan_account(id),
            field_key          text NOT NULL,
            value_type         value_type,
            value_raw          text,
            value_normalized   jsonb,
            is_absent          boolean NOT NULL DEFAULT false,
            confidence         numeric(4,3),
            char_span_start    int,
            char_span_end      int,
            quoted_span        text,
            span_verified      boolean NOT NULL DEFAULT false,
            span_truncated     boolean NOT NULL DEFAULT false,
            extractor_model    text,
            extractor_adapter  text,
            serving_mode       serving_mode,
            prompt_version     text,
            extraction_run_id  uuid NOT NULL,
            created_at         timestamptz NOT NULL DEFAULT now(),
            CHECK (is_absent OR value_normalized IS NOT NULL),
            CHECK (NOT is_absent OR (value_raw IS NULL AND quoted_span IS NULL))
        )
        """
    )
    op.execute("CREATE INDEX ix_fact_lookup ON extracted_fact (tenant_id, loan_account_id, field_key)")
    op.execute("CREATE INDEX ix_fact_doc    ON extracted_fact (document_id)")

    op.execute(
        """
        CREATE TABLE fact_conflict (
            id              uuid PRIMARY KEY,
            tenant_id       uuid NOT NULL REFERENCES tenant(id),
            loan_account_id uuid NOT NULL REFERENCES loan_account(id),
            group_key       text NOT NULL,
            field_key       text NOT NULL,
            fact_a_id       uuid NOT NULL REFERENCES extracted_fact(id) ON DELETE CASCADE,
            fact_b_id       uuid NOT NULL REFERENCES extracted_fact(id) ON DELETE CASCADE,
            conflict_type   conflict_type NOT NULL,
            delta           jsonb NOT NULL,
            operator        text  NOT NULL,
            resolved_status text  NOT NULL DEFAULT 'open',
            detected_at     timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, group_key, fact_a_id, fact_b_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fact_conflict")
    op.execute("DROP TABLE IF EXISTS extracted_fact")
    op.execute("DROP TABLE IF EXISTS document")
