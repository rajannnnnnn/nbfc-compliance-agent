"""FastAPI app factory. LLD §15 / M2-T04, M2-T07, M2-T06 metrics follow-up."""

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response as StarletteResponse
from uuid6 import uuid7

from app.api.errors import APIError, api_error_handler, unhandled_error_handler
from app.api.v1.router import router as v1_router
from app.boot import boot_or_exit
from app.config import get_settings
from app.db.engine import get_sessionmaker
from app.obs.logging import bind_request_context, clear_request_context, configure_logging
from app.obs.metrics import http_request_duration_seconds, http_requests_total


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    sessionmaker = get_sessionmaker(settings)
    async with sessionmaker() as session:
        await boot_or_exit(session, settings)
    yield


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="ClauseCheck", version="1.0", lifespan=_lifespan)

    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[StarletteResponse]]
    ) -> StarletteResponse:
        request_id = request.headers.get("X-Request-Id") or f"req_{uuid7()}"
        request.state.request_id = request_id
        bind_request_context(request_id=request_id)
        start = time.monotonic()
        try:
            response = await call_next(request)
        finally:
            clear_request_context()
        response.headers["X-Request-Id"] = request_id

        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)
        http_requests_total.labels(
            method=request.method, route=route_path, status=response.status_code
        ).inc()
        http_request_duration_seconds.labels(method=request.method, route=route_path).observe(
            time.monotonic() - start
        )
        return response

    # Demo frontend is a static page hosted on a different origin; auth is a manually-set
    # Bearer header, never a cookie, so a wildcard origin carries no credential-leak risk.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(APIError, api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.include_router(v1_router)

    # Recruiter-facing demo page: static, same-origin, served by this same container at
    # zero additional infrastructure cost. Real captured pipeline output ships alongside
    # the page (app/static/demo/sample_result.json) so it has something to show before
    # anyone clicks "run live".
    app.mount("/demo", StaticFiles(directory="app/static/demo", html=True), name="demo")

    return app


app = create_app()
