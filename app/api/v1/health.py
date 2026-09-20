"""/healthz, /readyz. LLD §15.4.

`/healthz` is liveness only — process up, nothing else. `/readyz` is the real check: database
reachable, an active corpus snapshot exists, and its pinning validates against the live
clause table. `fail_boot_on_pinning_mismatch` (app/config.py) kills the *process* at startup
on a pinning mismatch (M2-T07's boot assertion) — this endpoint re-checks pinning on every
call rather than caching a boolean, because a snapshot can be reactivated after boot without
a process restart, and a stale "ready" would be worse than the extra query.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from starlette.responses import Response

from app.config import Settings, get_settings
from app.corpus.pinning import PinningMismatchError, load_and_validate
from app.corpus.snapshot import get_active_snapshot_id
from app.db.engine import get_sessionmaker
from app.obs.metrics import REGISTRY, active_snapshot_age_seconds

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    sessionmaker = get_sessionmaker(settings)
    try:
        async with sessionmaker() as session:
            await session.execute(text("SELECT 1"))
            checks["database"] = "ok"

            snapshot_id = await get_active_snapshot_id(session)
            if snapshot_id is None:
                checks["corpus_snapshot"] = "no_active_snapshot"
                raise HTTPException(
                    status_code=503,
                    detail={"status": "not_ready", "checks": checks},
                )
            checks["corpus_snapshot"] = str(snapshot_id)

            await load_and_validate(snapshot_id, session, pinning_path="app/corpus/pinning.yaml")
            checks["pinning"] = "ok"
    except PinningMismatchError as exc:
        checks["pinning"] = str(exc)
        raise HTTPException(
            status_code=503, detail={"status": "not_ready", "checks": checks}
        ) from exc

    return {"status": "ready", "checks": checks}


@router.get("/metrics")
async def metrics(settings: Settings = Depends(get_settings)) -> Response:
    sessionmaker = get_sessionmaker(settings)
    async with sessionmaker() as session:
        row = (
            await session.execute(
                text("SELECT created_at FROM corpus_snapshot WHERE is_active = true")
            )
        ).first()
    if row is not None:
        age = (datetime.now(UTC) - row.created_at).total_seconds()
        active_snapshot_age_seconds.set(age)

    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
