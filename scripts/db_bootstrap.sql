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
