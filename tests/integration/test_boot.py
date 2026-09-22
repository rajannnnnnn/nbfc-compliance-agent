"""M2-T07: boot-time assertions, LLD §2. Each proves the underlying check actually rejects a
broken state, not just that it accepts a good one — a healthy DB is already exercised by
every other integration test that runs after migration."""

import pytest
from sqlalchemy import text as sqltext
from sqlalchemy.exc import IntegrityError

from app.boot import BootAssertionError, run_boot_assertions
from app.config import Settings, get_settings
from app.corpus.service import ingest
from app.db.engine import get_sessionmaker

pytestmark = pytest.mark.integration


@pytest.fixture
async def clean_snapshot():
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        await session.execute(sqltext("TRUNCATE corpus_snapshot CASCADE"))
        await session.commit()
    report = await ingest(settings=settings, activate=True)
    return report.snapshot_id


async def test_passes_against_a_correctly_migrated_and_ingested_database(clean_snapshot):
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        await run_boot_assertions(session, settings)  # must not raise


async def test_zero_active_snapshots_fails():
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        await session.execute(sqltext("UPDATE corpus_snapshot SET is_active = false"))
        await session.commit()
        with pytest.raises(BootAssertionError, match="exactly one active"):
            await run_boot_assertions(session, settings)


async def test_two_active_snapshots_is_impossible_at_the_db_level(clean_snapshot):
    """`uq_snapshot_active` (a partial unique index on `is_active` where true) makes this
    state unreachable at all — a stronger guarantee than a boot-time check, and the reason
    `run_boot_assertions` never actually observes more than one active row in practice."""
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        with pytest.raises(IntegrityError, match="uq_snapshot_active"):
            await session.execute(
                sqltext(
                    "INSERT INTO corpus_snapshot (id, instrument_manifest, embedding_model, "
                    "embedding_dimension, parser_version, chunk_count, is_active) "
                    "VALUES (gen_random_uuid(), '[]'::jsonb, 'x', :dim, 'x', 0, true)"
                ),
                {"dim": settings.embedding_dimension},
            )


async def test_embedding_dimension_mismatch_fails(clean_snapshot):
    settings = get_settings()
    sm = get_sessionmaker(settings)
    bad_settings = Settings(
        database_url=settings.database_url,
        embedding_dimension=settings.embedding_dimension + 1,
    )
    async with sm() as session:
        with pytest.raises(BootAssertionError, match="embedding_dimension"):
            await run_boot_assertions(session, bad_settings)


async def test_unresolved_pinning_path_fails(clean_snapshot):
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        # Deleting a pinned clause (e.g. RBC2025/p35, pinned for a docs-release field)
        # reproduces an unresolved pinning path without touching pinning.yaml itself.
        await session.execute(
            sqltext("DELETE FROM clause WHERE snapshot_id = :sid AND clause_path = 'RBC2025/p35'"),
            {"sid": str(clean_snapshot)},
        )
        await session.commit()
        with pytest.raises(BootAssertionError, match="pinned clause path"):
            await run_boot_assertions(session, settings)


async def test_non_shadow_rule_with_unresolved_clause_path_fails(clean_snapshot):
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        # R01 cites RBC2025/p35. Marking RBC2025 rbi_verified takes R01 out of shadow mode
        # (per ADR-026), so its clause path must now resolve or boot must fail.
        await session.execute(
            sqltext(
                "UPDATE regulation_instrument SET verification_status = 'rbi_verified' "
                "WHERE snapshot_id = :sid AND code = 'RBC2025'"
            ),
            {"sid": str(clean_snapshot)},
        )
        await session.execute(
            sqltext("DELETE FROM clause WHERE snapshot_id = :sid AND clause_path = 'RBC2025/p35'"),
            {"sid": str(clean_snapshot)},
        )
        await session.commit()
        with pytest.raises(BootAssertionError, match="RBC2025/p35"):
            await run_boot_assertions(session, settings)


async def test_fail_boot_on_pinning_mismatch_false_rejected_outside_ci(clean_snapshot):
    settings = get_settings()
    sm = get_sessionmaker(settings)
    non_ci_settings = Settings(
        database_url=settings.database_url,
        fail_boot_on_pinning_mismatch=False,
        env="local",
    )
    async with sm() as session:
        with pytest.raises(BootAssertionError, match="only permitted when env='ci'"):
            await run_boot_assertions(session, non_ci_settings)


async def test_fail_boot_on_pinning_mismatch_false_accepted_in_ci(clean_snapshot):
    settings = get_settings()
    sm = get_sessionmaker(settings)
    ci_settings = Settings(
        database_url=settings.database_url,
        fail_boot_on_pinning_mismatch=False,
        env="ci",
    )
    async with sm() as session:
        await run_boot_assertions(session, ci_settings)  # must not raise
