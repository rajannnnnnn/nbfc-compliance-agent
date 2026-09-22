from app.schema.generated import build_model_for_doc_type
from app.schema.registry import FieldRegistry

REAL_PATH = "app/schema/fields.yaml"


def test_builds_model_with_optional_fields():
    r = FieldRegistry(REAL_PATH)
    model = build_model_for_doc_type(r, "kfs")
    instance = model()  # every field optional — no args required
    assert instance.apr_bps.is_absent is True


def test_description_survives_into_json_schema():
    r = FieldRegistry(REAL_PATH)
    model = build_model_for_doc_type(r, "kfs")
    schema = model.model_json_schema()
    apr_prop = schema["properties"]["apr_bps"]
    assert "annualised" in apr_prop["description"].lower()


def test_only_fields_for_that_doc_type_are_present():
    r = FieldRegistry(REAL_PATH)
    model = build_model_for_doc_type(r, "call_transcript")
    fields = set(model.model_fields)
    assert "contact_datetime" in fields
    assert "apr_bps" not in fields
