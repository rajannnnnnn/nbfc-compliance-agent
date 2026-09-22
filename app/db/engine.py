"""Async engine, session factory, tenant session-var setter."""

from collections.abc import AsyncGenerator
from uuid import UUID

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings
from app.db.url import split_async_url

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine(settings: Settings) -> AsyncEngine:
    global _engine
    if _engine is None:
        url, connect_args = split_async_url(settings.database_url)
        _engine = create_async_engine(
            url,
            connect_args=connect_args,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_pre_ping=True,
        )
    return _engine


def get_sessionmaker(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(settings), expire_on_commit=False)
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def tenant_session(settings: Settings, tenant_id: UUID) -> AsyncGenerator[AsyncSession, None]:
    """Yields a session with app.tenant_id set for the transaction's lifetime. Every RLS-scoped
    query must go through this or an equivalent — a session that never sets the variable fails
    on its first query against a policy-protected table (LLD §3.7), which is the point."""
    sessionmaker = get_sessionmaker(settings)
    async with sessionmaker() as session:
        await set_tenant(session, tenant_id)
        yield session


async def set_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    from sqlalchemy import text

    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
    )
