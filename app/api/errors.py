"""Uniform error taxonomy. LLD §16.

Every error the API returns has this shape:
{"error": {"code": "...", "message": "...", "request_id": "...", "detail": {...}}}
"""

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

_CODE_TO_STATUS: dict[str, int] = {
    "CC-400-SCHEMA": 400,
    "CC-400-HASH-MISMATCH": 400,
    "CC-401-AUTH": 401,
    "CC-403-TENANT": 403,
    "CC-404-LOAN": 404,
    "CC-404-DOC": 404,
    "CC-404-CLAUSE": 404,
    "CC-409-IDEMPOTENCY": 409,
    "CC-409-DUPLICATE-DOC": 409,
    "CC-422-DOCTYPE-UNKNOWN": 422,
    "CC-422-NO-ASOF": 422,
    "CC-429-RATE": 429,
    "CC-500-INTERNAL": 500,
    "CC-503-CORPUS-UNAVAILABLE": 503,
    "CC-503-MODEL": 503,
}


class APIError(Exception):
    def __init__(self, code: str, message: str, *, detail: dict[str, Any] | None = None):
        if code not in _CODE_TO_STATUS:
            raise ValueError(f"unknown error code {code!r} — add it to _CODE_TO_STATUS first")
        self.code = code
        self.status_code = _CODE_TO_STATUS[code]
        self.message = message
        self.detail = detail or {}
        super().__init__(message)


def _body(error: APIError, request_id: str) -> dict[str, Any]:
    return {
        "error": {
            "code": error.code,
            "message": error.message,
            "request_id": request_id,
            "detail": error.detail,
        }
    }


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(status_code=exc.status_code, content=_body(exc, request_id))


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Anything that reaches here is a bug, not an expected failure mode — CLAUDE.md's
    invariants are enforced upstream (the validator, `require_as_of`, etc.), so this handler
    exists only so a client never sees a raw traceback, never so an unhandled exception is an
    acceptable steady state."""
    request_id = getattr(request.state, "request_id", "unknown")
    fallback = APIError("CC-500-INTERNAL", "internal error")
    return JSONResponse(status_code=500, content=_body(fallback, request_id))
