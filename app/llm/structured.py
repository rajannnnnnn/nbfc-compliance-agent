"""JSON-schema enforcement + one repair attempt. LLD §7.5."""

import json
from collections.abc import Callable

from pydantic import BaseModel, ValidationError


class StructuredOutputError(Exception):
    pass


def parse_or_repair(
    raw: str,
    model_cls: type[BaseModel],
    *,
    repair_fn: Callable[[str, str], str] | None = None,
) -> BaseModel:
    """Parses `raw` as JSON against `model_cls`. On failure, calls `repair_fn(raw, error)` — a
    sync callable returning a corrected string — exactly once, then gives up."""
    try:
        return model_cls.model_validate_json(raw)
    except (json.JSONDecodeError, ValidationError) as first_error:
        if repair_fn is None:
            raise StructuredOutputError(
                f"invalid structured output, no repair attempted: {first_error}"
            ) from first_error
        repaired = repair_fn(raw, str(first_error))
        try:
            return model_cls.model_validate_json(repaired)
        except (json.JSONDecodeError, ValidationError) as second_error:
            raise StructuredOutputError(
                f"invalid structured output after one repair attempt: {second_error}"
            ) from second_error
