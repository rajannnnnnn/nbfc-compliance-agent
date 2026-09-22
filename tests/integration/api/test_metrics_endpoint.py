"""GET /metrics — unauthenticated, Prometheus text format. Also proves the HTTP middleware
actually records cc_http_requests_total for a real request, not just that the counter object
exists."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.obs import metrics

pytestmark = pytest.mark.integration


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_metrics_endpoint_is_unauthenticated_and_prometheus_formatted():
    async with await _client() as client:
        r = await client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "cc_http_requests_total" in r.text


async def test_http_middleware_records_request_metrics():
    before = metrics.http_requests_total.labels(
        method="GET", route="/healthz", status="200"
    )._value.get()

    async with await _client() as client:
        r = await client.get("/healthz")
    assert r.status_code == 200

    after = metrics.http_requests_total.labels(
        method="GET", route="/healthz", status="200"
    )._value.get()
    assert after == before + 1
