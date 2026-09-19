import pytest

from app.schema.registry import FieldRegistry, RegistryValidationError

REAL_PATH = "app/schema/fields.yaml"


def test_real_registry_has_82_keys():
    r = FieldRegistry(REAL_PATH)
    assert len(r.all_keys()) == 82


def test_real_registry_validates_clean():
    r = FieldRegistry(REAL_PATH)
    r.validate()  # must not raise


def test_for_doc_type_filters_correctly():
    r = FieldRegistry(REAL_PATH)
    kfs_fields = r.for_doc_type("kfs")
    keys = {f.key for f in kfs_fields}
    assert "apr_bps" in keys
    assert "grievance_officer_phone" in keys
    assert "contact_datetime" not in keys


def test_required_for_kfs():
    r = FieldRegistry(REAL_PATH)
    required = r.required_for("kfs")
    assert "apr_bps" in required
    assert "sanctioned_amount" in required


def test_get_raises_keyerror_for_unknown():
    r = FieldRegistry(REAL_PATH)
    with pytest.raises(KeyError):
        r.get("not_a_real_field")


def _write_and_load(tmp_path, yaml_text):
    p = tmp_path / "fields.yaml"
    p.write_text(yaml_text)
    return FieldRegistry(str(p))


def test_duplicate_keys_rejected(tmp_path):
    yaml_text = """
version: 1
fields:
  - key: x
    label: X
    type: string
    doc_types: [kfs]
    lifecycle_stage: sanction
    description: d
  - key: x
    label: X2
    type: string
    doc_types: [kfs]
    lifecycle_stage: sanction
    description: d2
"""
    r = _write_and_load(tmp_path, yaml_text)
    with pytest.raises(RegistryValidationError, match="duplicate"):
        r.validate()


def test_enum_without_values_rejected(tmp_path):
    yaml_text = """
version: 1
fields:
  - key: x
    label: X
    type: enum
    doc_types: [kfs]
    lifecycle_stage: sanction
    description: d
"""
    r = _write_and_load(tmp_path, yaml_text)
    with pytest.raises(RegistryValidationError, match="enum_values"):
        r.validate()


def test_unknown_doc_type_rejected(tmp_path):
    yaml_text = """
version: 1
fields:
  - key: x
    label: X
    type: string
    doc_types: [not_a_real_doc_type]
    lifecycle_stage: sanction
    description: d
"""
    r = _write_and_load(tmp_path, yaml_text)
    with pytest.raises(RegistryValidationError, match="doc_type"):
        r.validate()


def test_required_for_not_in_doc_types_rejected(tmp_path):
    yaml_text = """
version: 1
fields:
  - key: x
    label: X
    type: string
    doc_types: [kfs]
    lifecycle_stage: sanction
    required_for: [loan_agreement]
    description: d
"""
    r = _write_and_load(tmp_path, yaml_text)
    with pytest.raises(RegistryValidationError, match="required_for"):
        r.validate()


def test_unknown_normalisation_directive_rejected(tmp_path):
    yaml_text = """
version: 1
fields:
  - key: x
    label: X
    type: string
    doc_types: [kfs]
    lifecycle_stage: sanction
    normalisation: { bogus_directive: true }
    description: d
"""
    r = _write_and_load(tmp_path, yaml_text)
    with pytest.raises(RegistryValidationError, match="normalisation"):
        r.validate()


def test_field_referenced_but_undeclared_rejected():
    r = FieldRegistry(REAL_PATH)
    with pytest.raises(RegistryValidationError):
        r.validate_external_references({"apr_bps", "not_a_real_field_anyone_declared"})


def test_field_referenced_and_declared_passes():
    r = FieldRegistry(REAL_PATH)
    r.validate_external_references({"apr_bps", "contact_datetime"})
