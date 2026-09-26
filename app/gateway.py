"""Public edge process. LLD §15 follow-up (frontend/backend port split).

The backend (`app.main:app`, Uvicorn on 127.0.0.1:8000) is never exposed outside this
machine — Fly's `[http_service]` points only at this gateway's port. The gateway serves
the static frontend at the document root (no `/demo` path segment) and reverse-proxies
everything else to the backend over loopback, so the browser only ever talks to one
origin and one port. This is the same "several processes, one machine" shape as Redis +
Celery + Uvicorn in `scripts/start.sh` — the gateway is simply the one process Fly's edge
is allowed to reach.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

BACKEND_BASE_URL = "http://127.0.0.1:8000"
_API_PREFIXES = ("/v1", "/docs", "/redoc", "/openapi.json", "/healthz", "/readyz")
_HOP_BY_HOP_RESPONSE_HEADERS = {"content-encoding", "content-length", "transfer-encoding", "connection"}


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(base_url=BACKEND_BASE_URL, timeout=65.0) as client:
        app.state.backend = client
        yield


gateway = FastAPI(lifespan=_lifespan)


async def _proxy(request: Request, path: str) -> Response:
    client: httpx.AsyncClient = request.app.state.backend
    forward_headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    upstream = await client.request(
        request.method,
        f"/{path}",
        params=request.query_params,
        content=await request.body(),
        headers=forward_headers,
    )
    response_headers = {
        k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP_RESPONSE_HEADERS
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type"),
    )


async def _proxy_route(request: Request) -> Response:
    return await _proxy(request, request.url.path.lstrip("/"))


for _prefix in _API_PREFIXES:
    route_path = (
        _prefix
        if _prefix in ("/docs", "/redoc", "/openapi.json", "/healthz", "/readyz")
        else _prefix + "/{path:path}"
    )
    gateway.add_api_route(
        route_path,
        _proxy_route,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    )

# Everything not matched above (the frontend page and its static assets) is served from
# the document root — mounted last so it never shadows the API routes registered above.
gateway.mount("/", StaticFiles(directory="app/static/demo", html=True), name="frontend")
