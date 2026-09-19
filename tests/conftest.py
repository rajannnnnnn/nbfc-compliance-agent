"""pytest-asyncio creates a new event loop per test function by default; app.db.engine caches
a module-level engine/sessionmaker keyed to whichever loop created them. Without disposing
between tests, a second test's queries hit a connection bound to a closed loop. Dispose after
every test so each gets a fresh engine bound to its own loop."""

import pytest_asyncio

from app.db.engine import dispose_engine


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_after_test():
    yield
    await dispose_engine()
