"""Helpers to SET LOCAL app.tenant_id per transaction. Every Celery task that opens a session
does this itself, explicitly — a task that forgets fails on its first query (LLD §3.7)."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def require_tenant_scope(session: AsyncSession, tenant_id: UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
    )


async def current_tenant(session: AsyncSession) -> str | None:
    row = await session.execute(text("SELECT current_setting('app.tenant_id', true)"))
    val = row.scalar_one_or_none()
    return val or None
