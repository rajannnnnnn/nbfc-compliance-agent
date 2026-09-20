"""Celery app configuration. LLD §14.

Task payloads carry identifiers only — CLAUDE.md §2.3: "No document bytes persisted... not
in a Celery payload." Document text never crosses the broker; per ADR-017, extraction itself
runs synchronously inside the API request handler for exactly this reason, and only
`assess.document` (an id-only payload) is queued afterward.
"""

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

_settings = get_settings()

app = Celery("clausecheck", broker=_settings.redis_url, backend=_settings.redis_url)

app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    task_default_retry_delay=5,
    task_annotations={"*": {"max_retries": 3}},
    task_routes={
        "extract.*": {"queue": "extract"},
        "assess.*": {"queue": "assess"},
        "maintenance.*": {"queue": "maintenance"},
    },
    beat_schedule={
        "corpus-drift": {
            "task": "maintenance.corpus_drift",
            "schedule": crontab(hour=2, minute=0, day_of_week=1),
        },
        "retention": {
            "task": "maintenance.retention_sweep",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)

# Imported for side effect — registers every @app.task in these modules by name. Celery
# needs each task module imported once, somewhere, before a worker or `.delay()` caller can
# dispatch by name.
from app.tasks import assess_tasks, maintenance_tasks  # noqa: E402,F401
