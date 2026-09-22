"""Fly `release_command` entrypoint: migrate, then ingest only if no active
corpus_snapshot exists yet — corpus ingest calls Gemini's embedding API, whose free
tier is a few hundred requests/day (see .env's CC_EMBEDDING_API_KEY comment), so it
must not re-run on every deploy."""

import asyncio
import subprocess

from sqlalchemy import text

from app.corpus.service import ingest
from app.config import get_settings
from app.db.engine import dispose_engine, get_sessionmaker


async def _has_active_snapshot() -> bool:
    settings = get_settings()
    sessionmaker = get_sessionmaker(settings)
    async with sessionmaker() as session:
        row = (
            await session.execute(
                text("SELECT 1 FROM corpus_snapshot WHERE is_active = true LIMIT 1")
            )
        ).first()
    await dispose_engine()
    return row is not None


async def main() -> None:
    if await _has_active_snapshot():
        print("release: active corpus_snapshot already exists, skipping ingest")
        return
    print("release: no active corpus_snapshot, running ingest")
    report = await ingest(activate=True)
    print(f"release: ingest complete — {report}")


if __name__ == "__main__":
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    asyncio.run(main())
