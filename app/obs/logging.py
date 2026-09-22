"""structlog JSON configuration with the content denylist. LLD §18.

CLAUDE.md §5: "Log structured, log no content." The denylist processor drops any key named
here at serialisation time — a leak requires defeating this processor, not merely forgetting
to redact at the call site. This is the same defence-in-depth pattern as the citation
validator (app/verdict/validator.py): a structural guarantee, not a habit.
"""

import logging
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

DENYLIST_KEYS = frozenset(
    {
        "text",
        "document_text",
        "value_raw",
        "quoted_span",
        "prompt",
        "messages",
        "rationale",
    }
)

_REDACTED = "[REDACTED-BY-DENYLIST]"


def _scrub(value: Any) -> Any:
    """Recurses into dicts and lists so a denylisted key nested inside a structured value
    (e.g. `{"extra": {"prompt": "..."}}` or a list of per-field dicts) is caught too — a
    caller who logs `field_key`, `value=fact.model_dump()` should not need to remember that
    `value` might itself carry a `value_raw`."""
    if isinstance(value, Mapping):
        return {key: (_REDACTED if key in DENYLIST_KEYS else _scrub(v)) for key, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def drop_denylisted_keys(
    logger: object, method_name: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
    """A structlog processor: replaces any denylisted key's value rather than dropping the
    key entirely, so a log line that *should* have carried that field still shows it was
    present and scrubbed, rather than silently vanishing (which would look identical to the
    field never having been set — much harder to notice in an audit)."""
    for key, value in list(event_dict.items()):
        event_dict[key] = _REDACTED if key in DENYLIST_KEYS else _scrub(value)
    return event_dict


def configure_logging(*, json_output: bool = True, level: int = logging.INFO) -> None:
    """Call once at process start (API and worker both). Idempotent — safe to call more than
    once, e.g. once from app startup and again from a test fixture."""
    logging.basicConfig(stream=sys.stdout, level=level, format="%(message)s")

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            drop_denylisted_keys,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        # No explicit `file=` here: PrintLoggerFactory() resolves sys.stdout dynamically on
        # each write rather than capturing today's file object, which matters when a test
        # harness (or anything else) swaps sys.stdout out after configure_logging() ran.
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(**initial_context: Any) -> Any:
    return structlog.get_logger(**initial_context)


def bind_request_context(
    *,
    request_id: str,
    tenant_id: str | None = None,
    loan_account_id: str | None = None,
    document_id: str | None = None,
    stage: str | None = None,
    check_key: str | None = None,
) -> None:
    """Binds the standard context fields (LLD §18) to structlog's contextvars so every log
    line emitted for the rest of this request/task carries them without being re-passed."""
    context: dict[str, Any] = {"request_id": request_id}
    if tenant_id is not None:
        context["tenant_id"] = tenant_id
    if loan_account_id is not None:
        context["loan_account_id"] = loan_account_id
    if document_id is not None:
        context["document_id"] = document_id
    if stage is not None:
        context["stage"] = stage
    if check_key is not None:
        context["check_key"] = check_key
    structlog.contextvars.bind_contextvars(**context)


def clear_request_context() -> None:
    structlog.contextvars.clear_contextvars()
