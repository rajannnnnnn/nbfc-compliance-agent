"""M2-T05: Celery app configuration and task registration."""

import pytest

from app.tasks.celery_app import app

pytestmark = pytest.mark.integration


def test_task_routes_match_lld_14():
    routes = app.conf.task_routes
    assert routes["extract.*"] == {"queue": "extract"}
    assert routes["assess.*"] == {"queue": "assess"}
    assert routes["maintenance.*"] == {"queue": "maintenance"}


def test_reliability_settings():
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.worker_prefetch_multiplier == 1


def test_beat_schedule_has_both_entries():
    names = {entry["task"] for entry in app.conf.beat_schedule.values()}
    assert names == {"maintenance.corpus_drift", "maintenance.retention_sweep"}


def test_all_lld_14_tasks_are_registered():
    expected = {
        "assess.document",
        "assess.check",
        "assess.account",
        "maintenance.retention_sweep",
        "maintenance.corpus_drift",
    }
    assert expected.issubset(set(app.tasks.keys()))


def test_task_names_route_to_the_right_queue():
    router = app.amqp.router
    for name, queue in [
        ("assess.document", "assess"),
        ("assess.check", "assess"),
        ("assess.account", "assess"),
        ("maintenance.retention_sweep", "maintenance"),
        ("maintenance.corpus_drift", "maintenance"),
    ]:
        route = router.route({}, name)
        assert route["queue"].name == queue
