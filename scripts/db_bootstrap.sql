-- Run once against a fresh database, before `alembic upgrade head`.
-- Creates the non-superuser application role only. Table grants live in migration 0008
-- (ADR-008) because `GRANT ... ON ALL TABLES` here would grant on nothing — no table exists
-- yet at bootstrap time.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'cc_app') THEN
        CREATE ROLE cc_app LOGIN PASSWORD 'dev' NOBYPASSRLS;
    END IF;
END
$$;

-- M4-T03b: a numeral synonym dictionary so lexical search recalls a clause regardless of
-- whether it (or the query) spells a number as digits ("24") or words ("twenty-four") — see
-- docs/DECISIONS.md ADR-037. The .syn file must exist in the server's tsearch_data directory
-- before this runs; docker-compose mounts scripts/tsearch/numbers.syn there. Idempotent: both
-- blocks are no-ops on a database that already has them (re-running this script, or Alembic
-- re-applying migration 0010, must not fail).
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_ts_dict WHERE dictname = 'numbers_syn') THEN
        CREATE TEXT SEARCH DICTIONARY numbers_syn (TEMPLATE = synonym, SYNONYMS = numbers);
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_ts_config WHERE cfgname = 'clausecheck_en') THEN
        CREATE TEXT SEARCH CONFIGURATION clausecheck_en (COPY = english);
        ALTER TEXT SEARCH CONFIGURATION clausecheck_en
            ALTER MAPPING FOR asciiword, asciihword, hword_asciipart, word, hword, hword_part
            WITH numbers_syn, english_stem;
    END IF;
END
$$;
