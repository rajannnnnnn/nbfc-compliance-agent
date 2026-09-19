"""clause, clause_reference, indexes

Revision ID: 0005
Revises: 0004

Vector column width is read from Settings, never hardcoded (CLAUDE.md §3) — 1536, not the
LLD's literal 3072, because pgvector's HNSW index has a 2000-dimension ceiling and vector(3072)
cannot be indexed at all. See docs/DECISIONS.md ADR-004.

`applies_to_borrower_classes` is not in the LLD's own DDL — added per ADR-005 so the
applicability filter can express "this clause is scoped to microfinance borrowers only",
which is required to produce the PRD §11 temporal-pair behaviour at all.
"""
from alembic import op

from app.config import get_settings

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    dim = get_settings().embedding_dimension
    op.execute(
        f"""
        CREATE TABLE clause (
            id               uuid PRIMARY KEY,
            snapshot_id      uuid NOT NULL REFERENCES corpus_snapshot(id) ON DELETE CASCADE,
            instrument_id    uuid NOT NULL REFERENCES regulation_instrument(id) ON DELETE CASCADE,
            instrument_code  text NOT NULL,
            clause_path      text NOT NULL,
            chapter          text,
            chapter_title    text,
            section_letter   text,
            section_title    text,
            para_number      text NOT NULL,
            para_sort        int  NOT NULL,
            level2_label     text,
            level3_label     text,
            heading          text,
            text             text NOT NULL,
            text_with_stem   text NOT NULL,
            token_count      int  NOT NULL,
            chunk_kind       chunk_kind NOT NULL DEFAULT 'clause',
            chunk_strategy   text NOT NULL,
            chunk_index      int  NOT NULL,
            effective_from   date,
            effective_to     date,
            citable          boolean NOT NULL DEFAULT true,
            applies_to_borrower_classes text[] NOT NULL DEFAULT '{{}}',
            embedding        vector({dim}),
            tsv              tsvector GENERATED ALWAYS AS
                                (to_tsvector('english', coalesce(heading,'') || ' ' || text)) STORED,
            UNIQUE (snapshot_id, clause_path)
        )
        """
    )
    op.execute("CREATE INDEX ix_clause_vec  ON clause USING hnsw (embedding vector_cosine_ops)")
    op.execute("CREATE INDEX ix_clause_tsv  ON clause USING gin (tsv)")
    op.execute("CREATE INDEX ix_clause_eff  ON clause (snapshot_id, effective_from, effective_to)")
    op.execute("CREATE INDEX ix_clause_para ON clause (instrument_id, para_sort, level2_label, level3_label)")
    op.execute("CREATE INDEX ix_clause_trgm ON clause USING gin (text gin_trgm_ops)")

    op.execute(
        """
        CREATE TABLE clause_reference (
            id                uuid PRIMARY KEY,
            snapshot_id       uuid NOT NULL REFERENCES corpus_snapshot(id) ON DELETE CASCADE,
            from_clause_id    uuid NOT NULL REFERENCES clause(id) ON DELETE CASCADE,
            to_instrument_code text NOT NULL,
            to_clause_path    text,
            reference_text    text NOT NULL,
            reference_kind    text NOT NULL CHECK (reference_kind IN
                                 ('incorporates','amends','repeals','see_also'))
        )
        """
    )
    op.execute("CREATE INDEX ix_ref_from ON clause_reference (from_clause_id, reference_kind)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS clause_reference")
    op.execute("DROP TABLE IF EXISTS clause")
