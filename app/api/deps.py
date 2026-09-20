"""FastAPI dependencies: request id, tenant resolution, RLS-scoped sessions."""

import hashlib
from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import APIError
from app.config import Settings, get_settings
from app.db.engine import get_sessionmaker
from app.llm.client import LLMClient

_TENANT_BY_HASH_SQL = "SELECT id FROM tenant WHERE api_key_hash = :hash AND is_active = true"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_request_id(request: Request) -> str:
    """Set by `RequestIdMiddleware` (app/main.py) before any dependency runs; every response
    carries the same value in `X-Request-Id` (LLD §15)."""
    return str(request.state.request_id)


async def get_tenant_id(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> UUID:
    """`CC-401-AUTH` on anything but a valid `Bearer <token>` that hashes to an active
    tenant's `api_key_hash` (ADR-030). No session is opened here — resolving the tenant and
    setting `app.tenant_id` are deliberately separate steps, so a caller that only needs the
    id (e.g. to build a request-scoped session itself) isn't forced through RLS setup twice."""
    if not authorization or not authorization.startswith("Bearer "):
        raise APIError("CC-401-AUTH", "missing or malformed Authorization header")
    token = authorization[len("Bearer ") :].strip()
    if not token:
        raise APIError("CC-401-AUTH", "empty bearer token")

    sessionmaker = get_sessionmaker(settings)
    async with sessionmaker() as session:
        row = (
            await session.execute(text(_TENANT_BY_HASH_SQL), {"hash": hash_token(token)})
        ).first()
    if row is None:
        raise APIError("CC-401-AUTH", "invalid or inactive token")
    return UUID(str(row.id))


async def get_tenant_session(
    tenant_id: UUID = Depends(get_tenant_id),
) -> AsyncGenerator[AsyncSession, None]:
    """Yields a session with `app.tenant_id` set for the request's lifetime — every
    RLS-protected query in a request handler must go through this dependency or the
    equivalent `tenant_session()` helper (app/db/engine.py); a session that never sets the
    variable fails on its first query against a policy-protected table, which is the point."""
    settings = get_settings()
    sessionmaker = get_sessionmaker(settings)
    async with sessionmaker() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
        )
        yield session


def get_llm_client(settings: Settings = Depends(get_settings)) -> LLMClient:
    """A `Depends`-injectable seam, not just a convenience: overriding this in
    `app.dependency_overrides` is how a test swaps in a stub client (fixed embeddings, a
    scripted `structured()` response) without ever making a real network call, the same
    pattern every non-API test in this codebase already uses when it hands `assess_fact` or
    `extract_document` a fake `LLMClient`."""
    return LLMClient(settings)
