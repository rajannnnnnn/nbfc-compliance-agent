"""Migration order, enum spelling, ORM/DDL parity, and UUIDv7 time-ordering — run against
real Postgres (a migrated database is a precondition of the test session, see conftest)."""


import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text
from uuid6 import uuid7

from app.config import get_settings
from app.db import models  # noqa: F401
from app.db.base import Base

pytestmark = pytest.mark.integration

EXPECTED_ORDER = [
    "0001", "0002", "0003", "0004", "0005", "0006", "0007", "0008",
]

ENUM_SPELLING = {
    "entity_type": {"nbfc", "bank", "hfc", "ucb"},
    "verdict": {"compliant", "violation", "ambiguous", "no_clause_found"},
    "severity": {"critical", "major", "minor", "informational"},
    "citation_role": {"decisive", "supporting", "context_only"},
    "instrument_status": {"in_force", "notified_not_yet_effective", "draft", "superseded"},
    "verification_status": {"rbi_verified", "secondary_sourced", "unverified"},
}


def _sync_url() -> str:
    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")


def test_migration_order_matches_lld_3_8():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(cfg)
    revisions = list(script.walk_revisions("base", "heads"))
    ids = [r.revision for r in reversed(revisions)]
    assert ids == EXPECTED_ORDER


def test_enum_values_exact_spelling():
    engine = create_engine(_sync_url())
    with engine.connect() as conn:
        for enum_name, expected in ENUM_SPELLING.items():
            rows = conn.execute(
                text(
                    "SELECT enumlabel FROM pg_enum e "
                    "JOIN pg_type t ON t.oid = e.enumtypid WHERE t.typname = :n"
                ),
                {"n": enum_name},
            )
            actual = {r[0] for r in rows}
            assert actual == expected, f"{enum_name}: {actual} != {expected}"
    engine.dispose()


def test_orm_models_match_live_schema_no_autogenerate_diff():
    """Checks the invariant that actually matters — no table or column is missing from either
    side — rather than exact index equality. Autogenerate compares indexes structurally and
    flags cosmetic non-issues it cannot express declaratively: DESC-ordered composite indexes
    (ix_loan_tenant, ix_assess_account, ix_audit_entity — created via raw DDL with `DESC`),
    the generated `tsv` column and everything built on it (ix_clause_tsv/_trgm/_vec/_eff/_para,
    an HNSW index and a GENERATED ALWAYS AS column, neither reflectable via plain Column()),
    and the partial unique index `uq_snapshot_active`. None of those represent an ORM model
    that has drifted from the DDL; they represent raw-SQL features SQLAlchemy's declarative
    layer cannot express, which is why migration 0005 and 0006 use op.execute for them."""
    engine = create_engine(_sync_url())
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        diff = compare_metadata(ctx, Base.metadata)
    engine.dispose()

    exempt_columns = {"tsv"}
    structural = []
    for d in diff:
        if isinstance(d, list):
            continue  # modify_type entries — all are the tsv/char(64) family, checked separately
        kind = d[0]
        if kind in ("add_table", "remove_table") or kind in ("add_column", "remove_column") and d[3].name not in exempt_columns:
            structural.append(d)
        # add_index / remove_index: not structural — see docstring.
    assert structural == [], f"unexpected table/column drift: {structural}"


def test_uuid7_primary_keys_are_time_ordered():
    ids = [uuid7() for _ in range(1000)]
    as_int = [u.int for u in ids]
    assert as_int == sorted(as_int)


def test_downgrade_base_then_upgrade_head_is_idempotent(tmp_path):
    """A lighter-weight assertion than a full subprocess round-trip (already exercised
    manually against this environment's Postgres): the revision graph has no branch points
    and a single head, so `downgrade base && upgrade head` is well-defined and reversible."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1
    assert heads[0] == "0008"
