"""ADR-041: a doc_type with more registered fields than `_MAX_FIELDS_PER_CALL` is split into
several schema-constrained calls (each sent the full document text) rather than one call
whose schema a provider's structured-output mode may reject outright for being too large.
No real model is used here — a stub client proves the splitting/merging mechanics."""

from app.extract.extractor import _MAX_FIELDS_PER_CALL, extract_raw_fields
from app.schema.generated import FieldExtraction
from app.schema.registry import FieldRegistry


class _StubClient:
    def __init__(self):
        self.calls: list[list[str]] = []

    async def structured(self, *, model_cls, model, messages, stage, adapter_id=None):
        field_keys = list(model_cls.model_fields)
        self.calls.append(field_keys)
        values = {
            key: FieldExtraction(value_raw=f"val-{key}", is_absent=False, quoted_span=key)
            for key in field_keys
        }
        instance = model_cls.model_validate(values)
        return instance, None


async def test_small_doc_type_makes_a_single_call():
    registry = FieldRegistry("app/schema/fields.yaml")
    assert len(registry.for_doc_type("sanction_letter")) <= _MAX_FIELDS_PER_CALL
    client = _StubClient()

    class _Settings:
        extract_model = "openai/gpt-4o"
        extract_adapter_id = None

    result = await extract_raw_fields(
        document_text="irrelevant",
        doc_type="sanction_letter",
        client=client,
        registry=registry,
        settings=_Settings(),
    )

    assert len(client.calls) == 1
    dumped = result.model_dump()
    assert set(dumped) == {spec.key for spec in registry.for_doc_type("sanction_letter")}
    assert all(not v["is_absent"] for v in dumped.values())


async def test_large_doc_type_splits_into_multiple_calls_and_merges_results():
    registry = FieldRegistry("app/schema/fields.yaml")
    field_count = len(registry.for_doc_type("loan_agreement"))
    assert field_count > _MAX_FIELDS_PER_CALL
    client = _StubClient()

    class _Settings:
        extract_model = "openai/gpt-4o"
        extract_adapter_id = None

    result = await extract_raw_fields(
        document_text="irrelevant",
        doc_type="loan_agreement",
        client=client,
        registry=registry,
        settings=_Settings(),
    )

    expected_calls = (field_count + _MAX_FIELDS_PER_CALL - 1) // _MAX_FIELDS_PER_CALL
    assert len(client.calls) == expected_calls
    for call_fields in client.calls:
        assert len(call_fields) <= _MAX_FIELDS_PER_CALL

    all_called_fields = {k for call in client.calls for k in call}
    expected_fields = {spec.key for spec in registry.for_doc_type("loan_agreement")}
    assert all_called_fields == expected_fields

    dumped = result.model_dump()
    assert set(dumped) == expected_fields
    assert all(not v["is_absent"] and v["value_raw"] == f"val-{k}" for k, v in dumped.items())
