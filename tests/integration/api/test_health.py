"""M2-T04 acceptance: /healthz, /readyz, /v1/corpus.

Uses `httpx.AsyncClient` over `ASGITransport` rather than `fastapi.testclient.TestClient` —
the sync `TestClient` runs the app in a separate thread with its own event loop, which
collides with this codebase's cached module-level SQLAlchemy engine (bound to whichever loop
first used it) the moment a test also touches the database directly, the same class of bug
`tests/conftest.py`'s `dispose_engine()` fixture exists to prevent across tests. Driving the
app through the same pytest-asyncio loop as everything else avoids it entirely.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sqltext

from app.config import get_settings
from app.corpus.service import ingest
from app.db.engine import get_sessionmaker
from app.main import app

pytestmark = pytest.mark.integration


@pytest.fixture
async def active_snapshot():
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        await session.execute(sqltext("TRUNCATE corpus_snapshot CASCADE"))
        await session.commit()
    return await ingest(settings=settings, activate=True)


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_healthz_is_liveness_only():
    async with await _client() as client:
        r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_readyz_503_with_no_active_snapshot():
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        await session.execute(sqltext("TRUNCATE corpus_snapshot CASCADE"))
        await session.commit()

    async with await _client() as client:
        r = await client.get("/readyz")
    assert r.status_code == 503


async def test_readyz_200_with_active_snapshot_and_valid_pinning(active_snapshot):
    async with await _client() as client:
        r = await client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["pinning"] == "ok"


async def test_corpus_manifest_is_unauthenticated_and_lists_instruments(active_snapshot):
    async with await _client() as client:
        r = await client.get("/v1/corpus")
    assert r.status_code == 200
    body = r.json()
    assert "instruments" in body
    assert len(body["instruments"]) == 5
    for inst in body["instruments"]:
        assert "verification_status" in inst
