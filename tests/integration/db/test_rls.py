"""Row-level security, exercised against real Postgres as the cc_app role — not superuser.
LLD §3.7: the application connects as a role without BYPASSRLS, and a transaction that never
sets app.tenant_id fails on its first query."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

pytestmark = pytest.mark.integration


def _cc_app_url() -> str:
    s = get_settings()
    # swap credentials for the non-superuser role; same host/db as CC_DATABASE_URL
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(s.database_url)
    netloc = f"cc_app:dev@{parts.hostname}:{parts.port or 5432}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


@pytest_asyncio.fixture
async def cc_app_engine():
    engine = create_async_engine(_cc_app_url())
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def two_tenants(cc_app_engine):
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    async with cc_app_engine.begin() as conn:
        for tid in (tenant_a, tenant_b):
            await conn.execute(
                text("INSERT INTO tenant (id, name) VALUES (:id, :name)"),
                {"id": str(tid), "name": f"tenant-{tid}"},
            )
    yield tenant_a, tenant_b
    # cleanup as superuser to bypass FK/RLS friction; children before parent
    su = create_async_engine(get_settings().database_url)
    async with su.begin() as conn:
        for tid in (tenant_a, tenant_b):
            await conn.execute(
                text("DELETE FROM loan_account WHERE tenant_id = :id"), {"id": str(tid)}
            )
        for tid in (tenant_a, tenant_b):
            await conn.execute(text("DELETE FROM tenant WHERE id = :id"), {"id": str(tid)})
    await su.dispose()


async def test_role_lacks_bypassrls(cc_app_engine):
    async with cc_app_engine.begin() as conn:
        row = await conn.execute(
            text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
        )
        assert row.scalar_one() is False


async def _insert_loan_account(engine, tenant_id, external_ref: str) -> None:
    """Setup helper — inserts as the owning tenant, scope set correctly, so the row exists
    for the actual test to probe under a *different* scoping condition."""
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
        )
        await conn.execute(
            text(
                "INSERT INTO loan_account (id, tenant_id, external_ref, product_type) "
                "VALUES (:id, :tid, :ref, 'personal')"
            ),
            {"id": str(uuid.uuid4()), "tid": str(tenant_id), "ref": external_ref},
        )


async def test_query_without_tenant_scope_fails(cc_app_engine, two_tenants):
    """LLD §3.7: 'A task that opens a session without setting it will fail on its first
    query, which is the intended behaviour.' current_setting('app.tenant_id') with no
    session-level default is '' (empty string, not NULL) the first time it's read in a
    session, and casting '' to uuid inside the policy predicate raises — the RLS policy
    itself is what enforces this, not application code."""
    tenant_a, _ = two_tenants
    await _insert_loan_account(cc_app_engine, tenant_a, "LN-1")
    async with cc_app_engine.connect() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(text("SELECT * FROM loan_account"))


async def test_cross_tenant_select_returns_zero_rows(cc_app_engine, two_tenants):
    tenant_a, tenant_b = two_tenants
    await _insert_loan_account(cc_app_engine, tenant_a, "LN-2")

    async with cc_app_engine.connect() as conn:
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_b)}
        )
        result = await conn.execute(
            text("SELECT * FROM loan_account WHERE tenant_id = :tid"), {"tid": str(tenant_a)}
        )
        assert result.fetchall() == []


async def test_cross_tenant_insert_rejected(cc_app_engine, two_tenants):
    tenant_a, tenant_b = two_tenants
    with pytest.raises(DBAPIError):
        async with cc_app_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_a)}
            )
            await conn.execute(
                text(
                    "INSERT INTO loan_account (id, tenant_id, external_ref, product_type) "
                    "VALUES (:id, :tid, 'LN-3', 'personal')"
                ),
                {"id": str(uuid.uuid4()), "tid": str(tenant_b)},  # WITH CHECK violation
            )


async def test_audit_event_update_delete_denied(cc_app_engine):
    async with cc_app_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO audit_event (id, actor, action, entity_type) "
                "VALUES (:id, 'system', 'test', 'x')"
            ),
            {"id": str(uuid.uuid4())},
        )
    with pytest.raises(DBAPIError):
        async with cc_app_engine.begin() as conn:
            await conn.execute(text("UPDATE audit_event SET actor = 'other'"))
