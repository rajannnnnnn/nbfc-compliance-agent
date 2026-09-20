"""Scheduled maintenance tasks. LLD §14.

Both are stubs pending a fuller build (M8): `retention_sweep` needs the tenant retention
policy (`tenant.retention_days`) wired to actual row deletion, and `corpus_drift` needs
`app.corpus.service.verify()` wired to alerting (`cc_corpus_drift_status`, LLD §18). Neither
belongs to M2's "wiring exists and routes correctly" scope — this module exists so
`app.tasks.celery_app`'s beat schedule has real task names to point at, and so the queue
round-trip (M2-T05's own acceptance test) has something registered on the `maintenance` queue
to dispatch.
"""

from typing import Any

from app.tasks.celery_app import app


@app.task(name="maintenance.retention_sweep")  # type: ignore[untyped-decorator]
def retention_sweep() -> dict[str, Any]:
    return {"status": "not_implemented"}


@app.task(name="maintenance.corpus_drift")  # type: ignore[untyped-decorator]
def corpus_drift() -> dict[str, Any]:
    return {"status": "not_implemented"}
