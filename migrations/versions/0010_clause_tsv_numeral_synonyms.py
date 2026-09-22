"""clause.tsv uses a numeral synonym text search configuration

Revision ID: 0010
Revises: 0009

M4-T03b (see docs/DECISIONS.md ADR-037): `clause.tsv` was generated with
`to_tsvector('english', ...)`, so a lexical query for a digit ("24") never matched a clause
that spells the same number as words ("twenty-four") and vice versa — proven directly against
the real ingested corpus in `tests/integration/retrieve/test_lexical_numeric_recall.py`.
`scripts/db_bootstrap.sql` creates a `numbers_syn` synonym dictionary (from
`scripts/tsearch/numbers.syn`, mounted into the server's tsearch_data directory) and a
`clausecheck_en` text search configuration that folds both spellings to the same token before
`english_stem` runs. This migration switches `clause.tsv`'s generation expression to that
configuration. A generated column's expression cannot be altered in place, so the column and
its GIN index are dropped and recreated identically except for the configuration name;
existing rows recompute automatically from `heading`/`text`, which is why this must run
through Alembic (recorded, reversible) rather than a one-off script.
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_UP_EXPR = "to_tsvector('clausecheck_en', coalesce(heading,'') || ' ' || text)"
_DOWN_EXPR = "to_tsvector('english', coalesce(heading,'') || ' ' || text)"


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_clause_tsv")
    op.execute("ALTER TABLE clause DROP COLUMN tsv")
    op.execute(
        f"ALTER TABLE clause ADD COLUMN tsv tsvector GENERATED ALWAYS AS ({_UP_EXPR}) STORED"
    )
    op.execute("CREATE INDEX ix_clause_tsv ON clause USING gin (tsv)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_clause_tsv")
    op.execute("ALTER TABLE clause DROP COLUMN tsv")
    op.execute(
        f"ALTER TABLE clause ADD COLUMN tsv tsvector GENERATED ALWAYS AS ({_DOWN_EXPR}) STORED"
    )
    op.execute("CREATE INDEX ix_clause_tsv ON clause USING gin (tsv)")
