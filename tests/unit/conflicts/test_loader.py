import pytest

from app.conflicts.loader import ConflictValidationError, load


def test_loads_real_conflicts_yaml():
    registry = load()
    assert len(registry.groups) == 3
    keys = {g.key for g in registry.groups}
    assert keys == {"apr", "closure_release_window", "cure_notice_sequence"}


def test_every_raises_check_is_a_registered_rule_id():
    registry = load()
    for g in registry.groups:
        assert g.raises_check


def test_groups_containing_matches_doc_type_and_field():
    registry = load()
    groups = registry.groups_containing(doc_type="kfs", field_key="apr_bps")
    assert [g.key for g in groups] == ["apr"]

    groups = registry.groups_containing(doc_type="kfs", field_key="loan_type")
    assert groups == []


def test_unknown_field_rejected(tmp_path):
    bad = tmp_path / "conflicts.yaml"
    bad.write_text("""
version: 1
groups:
  - key: bogus
    members:
      - {doc_type: kfs, field: not_a_real_field}
      - {doc_type: loan_agreement, field: apr_bps}
    operator: equal
    raises_check: R03_apr_consistency
""")
    with pytest.raises(ConflictValidationError, match="not declared in fields.yaml"):
        load(bad)


def test_unknown_doc_type_rejected(tmp_path):
    bad = tmp_path / "conflicts.yaml"
    bad.write_text("""
version: 1
groups:
  - key: bogus
    members:
      - {doc_type: not_a_real_doctype, field: apr_bps}
      - {doc_type: loan_agreement, field: apr_bps}
    operator: equal
    raises_check: R03_apr_consistency
""")
    with pytest.raises(ConflictValidationError, match="doc_type enum"):
        load(bad)


def test_field_not_listed_for_doc_type_rejected(tmp_path):
    bad = tmp_path / "conflicts.yaml"
    bad.write_text("""
version: 1
groups:
  - key: bogus
    members:
      - {doc_type: closure_statement, field: apr_bps}
      - {doc_type: loan_agreement, field: apr_bps}
    operator: equal
    raises_check: R03_apr_consistency
""")
    with pytest.raises(ConflictValidationError, match="does not list doc_type"):
        load(bad)


def test_unknown_raises_check_rejected(tmp_path):
    bad = tmp_path / "conflicts.yaml"
    bad.write_text("""
version: 1
groups:
  - key: bogus
    members:
      - {doc_type: kfs, field: apr_bps}
      - {doc_type: loan_agreement, field: apr_bps}
    operator: equal
    raises_check: R999_not_real
""")
    with pytest.raises(ConflictValidationError, match="not a registered rule id"):
        load(bad)


def test_equal_within_requires_tolerance(tmp_path):
    bad = tmp_path / "conflicts.yaml"
    bad.write_text("""
version: 1
groups:
  - key: bogus
    members:
      - {doc_type: kfs, field: apr_bps}
      - {doc_type: loan_agreement, field: apr_bps}
    operator: equal_within
    raises_check: R03_apr_consistency
""")
    with pytest.raises(Exception, match="equal_within requires tolerance"):
        load(bad)


def test_date_order_requires_valid_direction(tmp_path):
    bad = tmp_path / "conflicts.yaml"
    bad.write_text("""
version: 1
groups:
  - key: bogus
    members:
      - {doc_type: closure_statement, field: full_repayment_date}
      - {doc_type: docs_release_ack, field: original_docs_released_date}
    operator: date_order
    params: {direction: sideways}
    raises_check: R01_docs_release_30d
""")
    with pytest.raises(Exception, match="direction"):
        load(bad)
