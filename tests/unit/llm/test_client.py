from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import litellm
import pytest

from app.config import Settings
from app.llm.client import (
    CircuitBreaker,
    LLMClient,
    PermanentLLMError,
    TransientLLMError,
    _inlined_json_schema,
)
from app.llm.structured import StructuredOutputError


def _settings(**kw) -> Settings:
    defaults = dict(
        database_url="postgresql+asyncpg://u:p@localhost/db",
        llm_breaker_fail_threshold=3,
        llm_breaker_reset_s=60,
    )
    defaults.update(kw)
    return Settings(_env_file=None, **defaults)  # type: ignore[call-arg]


def _fake_response(tokens_in=10, tokens_out=5, content='{"ok": true}'):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=tokens_in, completion_tokens=tokens_out),
    )


class TestCircuitBreaker:
    def test_opens_after_threshold(self):
        cb = CircuitBreaker(fail_threshold=3, reset_s=60)
        assert not cb.is_open
        for _ in range(3):
            cb.record_failure()
        assert cb.is_open

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(fail_threshold=3, reset_s=60)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        assert not cb.is_open

    def test_resets_after_window(self, monkeypatch):
        cb = CircuitBreaker(fail_threshold=1, reset_s=0.01)
        cb.record_failure()
        assert cb.is_open
        import time

        time.sleep(0.02)
        assert not cb.is_open


async def test_retries_on_transient_only():
    client = LLMClient(_settings())
    with (
        patch("litellm.acompletion", new=AsyncMock(side_effect=litellm.Timeout("t", "m", "p"))),
        pytest.raises(TransientLLMError),
    ):
        await client.complete(model="openai/gpt-4o", messages=[], stage="extract")
    assert client.call_log[-1].outcome == "transient_error"


async def test_no_retry_on_permanent_error():
    client = LLMClient(_settings())
    with (
        patch(
            "litellm.acompletion",
            new=AsyncMock(side_effect=litellm.APIError(500, "bad", "openai", "gpt-4o")),
        ),
        pytest.raises(PermanentLLMError),
    ):
        await client.complete(model="openai/gpt-4o", messages=[], stage="extract")
    assert client.call_log[-1].outcome == "permanent_error"


async def test_bad_request_error_is_wrapped_as_permanent():
    """ADR-041: `litellm.BadRequestError` (e.g. a 400 from a provider rejecting a structured-
    output schema outright) does not subclass `litellm.APIError` in this litellm version —
    live-discovered when it propagated unwrapped past every caller that only catches this
    module's own error taxonomy. Must be wrapped into PermanentLLMError like any other
    permanent provider failure."""
    client = LLMClient(_settings())
    assert not issubclass(litellm.BadRequestError, litellm.APIError)
    with (
        patch(
            "litellm.acompletion",
            new=AsyncMock(
                side_effect=litellm.BadRequestError("schema too complex", "gpt-4o", "openai")
            ),
        ),
        pytest.raises(PermanentLLMError),
    ):
        await client.complete(model="openai/gpt-4o", messages=[], stage="extract")
    assert client.call_log[-1].outcome == "permanent_error"


async def test_breaker_opens_and_blocks_further_calls():
    client = LLMClient(_settings(llm_breaker_fail_threshold=2))
    with patch("litellm.acompletion", new=AsyncMock(side_effect=litellm.Timeout("t", "m", "p"))):
        for _ in range(2):
            with pytest.raises(TransientLLMError):
                await client.complete(model="openai/gpt-4o", messages=[], stage="extract")
    # third call should fail fast on the breaker without calling acompletion again
    with patch("litellm.acompletion", new=AsyncMock()) as mock_call:
        with pytest.raises(TransientLLMError, match="circuit open"):
            await client.complete(model="openai/gpt-4o", messages=[], stage="extract")
        mock_call.assert_not_called()


async def test_records_cost_and_tokens_on_success():
    client = LLMClient(_settings())
    with (
        patch("litellm.acompletion", new=AsyncMock(return_value=_fake_response())),
        patch("litellm.completion_cost", return_value=0.0021),
    ):
        content, record = await client.complete(model="openai/gpt-4o", messages=[], stage="verdict")
    assert content == '{"ok": true}'
    assert record.tokens_in == 10
    assert record.tokens_out == 5
    assert record.cost_usd == 0.0021
    assert record.outcome == "success"
    assert record.provider == "openai"


async def test_structured_repairs_once_then_fails():
    client = LLMClient(_settings())
    from pydantic import BaseModel

    class Out(BaseModel):
        x: int

    bad = _fake_response(content="not json")
    with (
        patch("litellm.acompletion", new=AsyncMock(return_value=bad)),
        patch("litellm.completion_cost", return_value=0.0),
        pytest.raises(StructuredOutputError),
    ):
        await client.structured(model_cls=Out, model="openai/gpt-4o", messages=[], stage="verdict")


async def test_structured_succeeds_first_try():
    client = LLMClient(_settings())
    from pydantic import BaseModel

    class Out(BaseModel):
        x: int

    good = _fake_response(content='{"x": 5}')
    with (
        patch("litellm.acompletion", new=AsyncMock(return_value=good)),
        patch("litellm.completion_cost", return_value=0.0),
    ):
        parsed, record = await client.structured(
            model_cls=Out, model="openai/gpt-4o", messages=[], stage="verdict"
        )
    assert parsed.x == 5


async def test_structured_passes_json_schema_response_format_not_bare_json_object():
    """ADR-038: `{"type": "json_object"}` only demands valid JSON, not any particular shape —
    live-discovered against Gemini, which validly returned a JSON array instead of the keyed
    object a per-doc-type extraction model requires. `structured()` must instead pass the
    actual JSON schema so shape is enforced structurally, not inferred by the model from
    prose."""
    client = LLMClient(_settings())
    from pydantic import BaseModel

    class Out(BaseModel):
        x: int

    good = _fake_response(content='{"x": 5}')
    with (
        patch("litellm.acompletion", new=AsyncMock(return_value=good)) as mock_call,
        patch("litellm.completion_cost", return_value=0.0),
    ):
        await client.structured(model_cls=Out, model="openai/gpt-4o", messages=[], stage="verdict")

    kwargs = mock_call.call_args.kwargs
    assert kwargs["response_format"]["type"] == "json_schema"
    assert kwargs["response_format"]["json_schema"]["name"] == "Out"
    assert (
        kwargs["response_format"]["json_schema"]["schema"]["properties"]["x"]["type"] == "integer"
    )


async def test_structured_repair_reuses_json_schema_response_format():
    client = LLMClient(_settings())
    from pydantic import BaseModel

    class Out(BaseModel):
        x: int

    bad = _fake_response(content="not json")
    good = _fake_response(content='{"x": 7}')
    with (
        patch("litellm.acompletion", new=AsyncMock(side_effect=[bad, good])) as mock_call,
        patch("litellm.completion_cost", return_value=0.0),
    ):
        parsed, _ = await client.structured(
            model_cls=Out, model="openai/gpt-4o", messages=[], stage="verdict"
        )
    assert parsed.x == 7
    assert mock_call.call_count == 2
    for call in mock_call.call_args_list:
        assert call.kwargs["response_format"]["type"] == "json_schema"


def test_inlined_json_schema_resolves_refs_for_nested_model():
    """Gemini's (and some other providers') schema mode rejects `$ref`/`$defs` — a nested
    model reused across multiple fields (as `FieldExtraction` is across every field of a
    per-doc-type extraction model) must be inlined at every use site."""
    from pydantic import BaseModel

    class Nested(BaseModel):
        value: str

    class Outer(BaseModel):
        a: Nested
        b: Nested

    schema = _inlined_json_schema(Outer)
    assert "$defs" not in schema
    assert "$ref" not in str(schema)
    assert schema["properties"]["a"]["properties"]["value"]["type"] == "string"
    assert schema["properties"]["b"]["properties"]["value"]["type"] == "string"
