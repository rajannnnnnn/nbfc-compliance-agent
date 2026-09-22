"""Boot-time assertions. LLD §2 / M2-T07. All fatal — a process that boots against a corpus
or schema it was not built for should never accept a request rather than fail loudly at
startup.
"""

import sys

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.corpus.pinning import PinningMismatchError, load_and_validate
from app.rules.registry import all_rules, is_shadow


class BootAssertionError(Exception):
    pass


async def _check_embedding_dimension(session: AsyncSession, settings: Settings) -> None:
    row = (
        await session.execute(
            text(
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid = 'clause'::regclass AND attname = 'embedding'"
            )
        )
    ).first()
    if row is None or row.atttypmod != settings.embedding_dimension:
        actual = row.atttypmod if row else None
        raise BootAssertionError(
            f"embedding_dimension={settings.embedding_dimension} does not match the live "
            f"clause.embedding column width ({actual})"
        )


async def _check_exactly_one_active_snapshot(session: AsyncSession) -> None:
    n = (
        await session.execute(text("SELECT COUNT(*) FROM corpus_snapshot WHERE is_active = true"))
    ).scalar_one()
    if n != 1:
        raise BootAssertionError(f"expected exactly one active corpus_snapshot, found {n}")


async def _check_pinning(session: AsyncSession, settings: Settings) -> None:
    if not settings.fail_boot_on_pinning_mismatch:
        if settings.env != "ci":
            raise BootAssertionError(
                "fail_boot_on_pinning_mismatch=false is only permitted when env='ci'"
            )
        return
    snapshot_row = (
        await session.execute(text("SELECT id FROM corpus_snapshot WHERE is_active = true"))
    ).first()
    if snapshot_row is None:
        return  # already caught by _check_exactly_one_active_snapshot
    try:
        await load_and_validate(snapshot_row.id, session, pinning_path="app/corpus/pinning.yaml")
    except PinningMismatchError as exc:
        raise BootAssertionError(str(exc)) from exc


async def _check_rule_clause_paths(session: AsyncSession) -> None:
    row = (
        await session.execute(text("SELECT id FROM corpus_snapshot WHERE is_active = true"))
    ).first()
    if row is None:
        return
    snapshot_id = row.id

    verification_rows = await session.execute(
        text(
            "SELECT code, verification_status FROM regulation_instrument WHERE snapshot_id = :sid"
        ),
        {"sid": str(snapshot_id)},
    )
    instrument_verification = {r.code: r.verification_status for r in verification_rows}

    unresolved: list[str] = []
    for rule_id, reg in all_rules().items():
        if is_shadow(rule_id, instrument_verification=instrument_verification):
            continue
        instance = reg.rule_cls()
        for path in instance.clause_paths:
            exists = (
                await session.execute(
                    text("SELECT 1 FROM clause WHERE snapshot_id = :sid AND clause_path = :path"),
                    {"sid": str(snapshot_id), "path": path},
                )
            ).first()
            if exists is None:
                unresolved.append(f"{rule_id}: {path}")
    if unresolved:
        raise BootAssertionError(
            f"{len(unresolved)} non-shadow rule clause path(s) do not resolve: {unresolved}"
        )


def _check_alembic_current_is_head(settings: Settings) -> None:
    sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(cfg)
    heads = set(script.get_heads())

    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            current = set(context.get_current_heads())
    finally:
        engine.dispose()

    if current != heads:
        raise BootAssertionError(f"alembic current {current} != heads {heads}")


async def run_boot_assertions(session: AsyncSession, settings: Settings) -> None:
    """Raises `BootAssertionError` on any failed assertion. Callers that want process exit
    (`app.main`'s lifespan) should catch it and call `sys.exit(1)`; tests call this directly
    to assert on the exception rather than the exit code."""
    _check_alembic_current_is_head(settings)
    await _check_exactly_one_active_snapshot(session)
    await _check_embedding_dimension(session, settings)
    await _check_pinning(session, settings)
    await _check_rule_clause_paths(session)


async def boot_or_exit(session: AsyncSession, settings: Settings) -> None:
    try:
        await run_boot_assertions(session, settings)
    except BootAssertionError as exc:
        print(f"FATAL: boot assertion failed: {exc}", file=sys.stderr)
        sys.exit(1)
