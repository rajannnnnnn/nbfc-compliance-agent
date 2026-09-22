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

A synonym dictionary's SYNONYMS file must exist on the Postgres server's own filesystem
(`$SHAREDIR/tsearch_data/numbers.syn`) — there is no way to load it over SQL. Managed
Postgres (Neon, RDS, Supabase, ...) gives no filesystem access, so `CREATE TEXT SEARCH
DICTIONARY` there always fails with "could not open synonym file". `upgrade()` attempts it
and falls back to plain `'english'` when it can't, so the deployment target decides the
outcome, not a hand edit of this file: self-hosted Postgres with `scripts/tsearch/numbers.syn`
mounted gets numeral-synonym recall, managed Postgres gets ordinary English search with
digit/word forms unmatched (`test_lexical_numeric_recall.py` is skipped there accordingly).
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_DOWN_EXPR = "to_tsvector('english', coalesce(heading,'') || ' ' || text)"


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_clause_tsv")
    op.execute("ALTER TABLE clause DROP COLUMN tsv")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_ts_dict WHERE dictname = 'numbers_syn') THEN
                BEGIN
                    CREATE TEXT SEARCH DICTIONARY numbers_syn (TEMPLATE = synonym, SYNONYMS = numbers);
                EXCEPTION WHEN OTHERS THEN
                    -- No filesystem access for tsearch_data (managed Postgres) — fall back
                    -- to plain 'english' below instead of failing the migration.
                    NULL;
                END;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_catalog.pg_ts_dict WHERE dictname = 'numbers_syn')
               AND NOT EXISTS (SELECT FROM pg_catalog.pg_ts_config WHERE cfgname = 'clausecheck_en') THEN
                CREATE TEXT SEARCH CONFIGURATION clausecheck_en (COPY = english);
                ALTER TEXT SEARCH CONFIGURATION clausecheck_en
                    ALTER MAPPING FOR asciiword, asciihword, hword_asciipart, word, hword, hword_part
                    WITH numbers_syn, english_stem;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        DECLARE
            cfg text := CASE
                WHEN EXISTS (SELECT FROM pg_catalog.pg_ts_config WHERE cfgname = 'clausecheck_en')
                THEN 'clausecheck_en' ELSE 'english'
            END;
        BEGIN
            EXECUTE format(
                $f$ALTER TABLE clause ADD COLUMN tsv tsvector
                    GENERATED ALWAYS AS (to_tsvector(%L, coalesce(heading,'') || ' ' || text)) STORED$f$,
                cfg
            );
        END
        $$;
        """
    )
    op.execute("CREATE INDEX ix_clause_tsv ON clause USING gin (tsv)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_clause_tsv")
    op.execute("ALTER TABLE clause DROP COLUMN tsv")
    op.execute(
        f"ALTER TABLE clause ADD COLUMN tsv tsvector GENERATED ALWAYS AS ({_DOWN_EXPR}) STORED"
    )
    op.execute("CREATE INDEX ix_clause_tsv ON clause USING gin (tsv)")
