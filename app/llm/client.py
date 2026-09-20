"""LiteLLM wrapper: routing, retries, breaker, accounting. LLD §7.5 / HLD §7.5.

This is the only module in the codebase that may import a provider SDK — LiteLLM itself
routes to the actual provider. CLAUDE.md §3: "No provider SDK imported outside app/llm/."
A test walks the AST of app/ to assert this (tests/unit/llm/test_no_provider_sdk_outside_llm.py).
"""

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import litellm
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.llm.structured import StructuredOutputError, parse_or_repair
from app.obs.metrics import (
    llm_breaker_state,
    llm_calls_total,
    llm_cost_usd_total,
    llm_duration_seconds,
    llm_tokens_total,
)


def _record_metrics(record: "CallRecord") -> None:
    llm_calls_total.labels(
        provider=record.provider, model=record.model, stage=record.stage, outcome=record.outcome
    ).inc()
    llm_duration_seconds.labels(
        provider=record.provider, model=record.model, stage=record.stage
    ).observe(record.wall_clock_ms / 1000)
    if record.outcome == "success":
        llm_tokens_total.labels(
            provider=record.provider, model=record.model, stage=record.stage, direction="in"
        ).inc(record.tokens_in)
        llm_tokens_total.labels(
            provider=record.provider, model=record.model, stage=record.stage, direction="out"
        ).inc(record.tokens_out)
        llm_cost_usd_total.labels(
            provider=record.provider, model=record.model, stage=record.stage
        ).inc(record.cost_usd)


class TransientLLMError(Exception):
    """Timeout, 429, 5xx, or the breaker being open. Retried by callers (LLD §14)."""


class PermanentLLMError(Exception):
    """Anything else — a bad request, an auth failure, a schema the provider rejects."""


@dataclass
class CallRecord:
    provider: str
    model: str
    adapter_id: str | None
    stage: str
    tokens_in: int
    tokens_out: int
    wall_clock_ms: int
    cost_usd: float
    outcome: str  # "success" | "transient_error" | "permanent_error"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class CircuitBreaker:
    """Per-provider. Opens after `fail_threshold` consecutive failures, resets after
    `reset_s` seconds — a half-open probe on the next call after that window."""

    def __init__(self, fail_threshold: int, reset_s: int):
        self.fail_threshold = fail_threshold
        self.reset_s = reset_s
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        return time.monotonic() - self._opened_at < self.reset_s

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.fail_threshold:
            self._opened_at = time.monotonic()


def _provider_of(model: str) -> str:
    return model.split("/", 1)[0] if "/" in model else "unknown"


_SCHEMA_KEYS_DROPPED_FOR_GENERATION = {
    "$defs",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "description",
    "title",
}


def _inline_refs(node: Any, defs: dict[str, Any]) -> Any:
    """Also strips numeric bound keywords (`minimum`/`maximum`/...) live-discovered against
    Gemini's structured-output mode: a bounded field (e.g. `FieldExtraction.confidence`,
    `ge=0.0, le=1.0`) repeated once per inlined field on a large per-doc-type schema (34
    fields for loan_agreement) produced a 400 "schema produces a constraint that has too
    many states for serving" — Gemini's own wording names exactly this pattern. These bounds
    are validation concerns, not generation-shape concerns: Pydantic still enforces them when
    the response is parsed back (`parse_or_repair`/`model_validate_json`), so dropping them
    from the schema shown to the provider loses no real safety."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if ref is not None:
            def_name = ref.rsplit("/", 1)[-1]
            return _inline_refs(defs[def_name], defs)
        any_of = node.get("anyOf")
        if isinstance(any_of, list) and len(any_of) == 2:
            non_null = [b for b in any_of if b.get("type") != "null"]
            has_null = any(b.get("type") == "null" for b in any_of)
            if has_null and len(non_null) == 1:
                # Pydantic's `X | None` becomes anyOf: [{type: X}, {type: null}] — Gemini's
                # constrained decoder counts each anyOf branch as extra states, which is what
                # tipped a 34-field schema (loan_agreement) over its "too many states" limit.
                # Gemini's own schema dialect uses a `nullable` flag instead of a union, so
                # collapse the common Optional-field case to that lighter form.
                collapsed = {**non_null[0], "nullable": True}
                for k in ("default",):
                    if k in node:
                        collapsed[k] = node[k]
                return _inline_refs(collapsed, defs)
        return {
            k: _inline_refs(v, defs)
            for k, v in node.items()
            if k not in _SCHEMA_KEYS_DROPPED_FOR_GENERATION
        }
    if isinstance(node, list):
        return [_inline_refs(item, defs) for item in node]
    return node


def _inlined_json_schema(model_cls: type[BaseModel]) -> dict[str, Any]:
    """Gemini's (and some other providers') structured-output schema mode does not support
    `$ref`/`$defs` — a nested Pydantic model (e.g. `FieldExtraction` reused across every field
    of an extraction schema) must appear inline at every use site, not as a shared reference.
    Pydantic's own `model_json_schema()` always emits `$defs` for any nested model, so this
    resolves every `$ref` against `$defs` and drops `$defs` from the result — see
    `_inline_refs` for the numeric-bound stripping this also performs."""
    schema = model_cls.model_json_schema()
    defs = schema.get("$defs", {})
    return cast(dict[str, Any], _inline_refs(schema, defs))


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._breakers: dict[str, CircuitBreaker] = {}
        self.call_log: list[CallRecord] = []

    def _breaker_for(self, provider: str) -> CircuitBreaker:
        if provider not in self._breakers:
            self._breakers[provider] = CircuitBreaker(
                self.settings.llm_breaker_fail_threshold, self.settings.llm_breaker_reset_s
            )
        return self._breakers[provider]

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        stage: str,
        adapter_id: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> tuple[str, CallRecord]:
        provider = _provider_of(model)
        breaker = self._breaker_for(provider)
        if breaker.is_open:
            raise TransientLLMError(f"circuit open for provider {provider}")

        start = time.monotonic()
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "api_key": self.settings.llm_api_key,
                "timeout": self.settings.llm_timeout_s,
            }
            if response_format is not None:
                kwargs["response_format"] = response_format
            resp = await litellm.acompletion(**kwargs)
        except (
            litellm.Timeout,  # type: ignore[attr-defined]
            litellm.RateLimitError,  # type: ignore[attr-defined]
            litellm.ServiceUnavailableError,  # type: ignore[attr-defined]
            litellm.APIConnectionError,  # type: ignore[attr-defined]
        ) as exc:
            breaker.record_failure()
            record = CallRecord(
                provider=provider,
                model=model,
                adapter_id=adapter_id,
                stage=stage,
                tokens_in=0,
                tokens_out=0,
                wall_clock_ms=int((time.monotonic() - start) * 1000),
                cost_usd=0.0,
                outcome="transient_error",
            )
            self.call_log.append(record)
            _record_metrics(record)
            llm_breaker_state.labels(provider=provider).set(1 if breaker.is_open else 0)
            raise TransientLLMError(str(exc)) from exc
        except litellm.APIError as exc:  # type: ignore[attr-defined]
            record = CallRecord(
                provider=provider,
                model=model,
                adapter_id=adapter_id,
                stage=stage,
                tokens_in=0,
                tokens_out=0,
                wall_clock_ms=int((time.monotonic() - start) * 1000),
                cost_usd=0.0,
                outcome="permanent_error",
            )
            self.call_log.append(record)
            _record_metrics(record)
            raise PermanentLLMError(str(exc)) from exc

        breaker.record_success()
        wall_ms = int((time.monotonic() - start) * 1000)
        usage = getattr(resp, "usage", None)
        tokens_in = getattr(usage, "prompt_tokens", 0) or 0
        tokens_out = getattr(usage, "completion_tokens", 0) or 0
        try:
            cost = litellm.completion_cost(completion_response=resp)
        except Exception:
            cost = 0.0

        record = CallRecord(
            provider=provider,
            model=model,
            adapter_id=adapter_id,
            stage=stage,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            wall_clock_ms=wall_ms,
            cost_usd=cost,
            outcome="success",
        )
        self.call_log.append(record)
        _record_metrics(record)
        llm_breaker_state.labels(provider=provider).set(0)
        content = resp.choices[0].message.content
        return content, record

    async def structured(
        self,
        *,
        model_cls: type[BaseModel],
        model: str,
        messages: list[dict[str, Any]],
        stage: str,
        adapter_id: str | None = None,
    ) -> tuple[BaseModel, CallRecord]:
        """Structured-output enforcement with one repair attempt (LLD §7.5).

        `response_format={"type": "json_object"}` only demands *valid JSON*, not any
        particular shape — found live against Gemini (ADR-038): with only a natural-language
        field table in the prompt and no example JSON, it validly returned a JSON *array* of
        field records instead of the keyed object `model_cls` requires, where GPT-family
        models happened to infer the object shape from context. Passing the actual JSON
        schema (`{"type": "json_schema", ...}`, OpenAI's format, translated per-provider by
        LiteLLM — including Gemini's `response_schema`) constrains the shape structurally
        instead of relying on the model to guess it from prose.
        """
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": model_cls.__name__,
                "schema": _inlined_json_schema(model_cls),
            },
        }
        raw, record = await self.complete(
            model=model,
            messages=messages,
            stage=stage,
            adapter_id=adapter_id,
            response_format=response_format,
        )

        def _repair(bad_output: str, error: str) -> str:
            # One synchronous repair pass is out of scope without a second model round-trip;
            # callers needing an actual model-driven repair should pass repair_fn explicitly.
            # Default: no repair possible from here, raises StructuredOutputError.
            raise StructuredOutputError(f"cannot repair without a second model call: {error}")

        try:
            parsed = parse_or_repair(raw, model_cls)
        except StructuredOutputError:
            # attempt one real repair round-trip against the same model
            repair_messages = messages + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        "Your previous response was not valid JSON matching the required "
                        "schema. Return ONLY corrected JSON, no prose."
                    ),
                },
            ]
            raw2, record2 = await self.complete(
                model=model,
                messages=repair_messages,
                stage=stage,
                adapter_id=adapter_id,
                response_format=response_format,
            )
            try:
                parsed = model_cls.model_validate_json(raw2)
            except (ValueError, ValidationError) as second_error:
                raise StructuredOutputError(
                    f"invalid structured output after one repair attempt: {second_error}"
                ) from second_error
            record = record2
        return parsed, record

    async def embed(self, texts: list[str], *, model: str, dimensions: int) -> list[list[float]]:
        try:
            resp = await litellm.aembedding(
                model=model,
                input=texts,
                api_key=self.settings.embedding_api_key,
                dimensions=dimensions,
            )
        except (
            litellm.Timeout,  # type: ignore[attr-defined]
            litellm.RateLimitError,  # type: ignore[attr-defined]
            litellm.ServiceUnavailableError,  # type: ignore[attr-defined]
            litellm.APIConnectionError,  # type: ignore[attr-defined]
        ) as exc:
            raise TransientLLMError(str(exc)) from exc
        except litellm.APIError as exc:  # type: ignore[attr-defined]
            raise PermanentLLMError(str(exc)) from exc
        return [item["embedding"] for item in resp.data]
