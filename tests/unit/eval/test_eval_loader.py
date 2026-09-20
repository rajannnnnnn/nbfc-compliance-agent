import pytest

from eval.loader import load_suite


def test_loads_real_suites():
    for suite in ("numeric_rules", "temporal", "abstention", "verdict", "adversarial"):
        cases = load_suite(suite)
        assert len(cases) > 0
        for case in cases:
            assert case.suite == suite


def test_missing_suite_raises():
    with pytest.raises(FileNotFoundError):
        load_suite("does_not_exist")


def test_mismatched_suite_field_rejected(tmp_path):
    suite_dir = tmp_path / "temporal"
    suite_dir.mkdir()
    (suite_dir / "bad.json").write_text("""
        {
          "case_ref": "EV-BAD-001",
          "suite": "numeric_rules",
          "stage": "verdict",
          "doc_type": "kfs",
          "event_date": "2026-01-01",
          "account_profile": {"product_type": "personal"},
          "expected": {"check_key": "F:x", "verdict": "no_clause_found"}
        }
        """)
    with pytest.raises(ValueError, match="suite"):
        load_suite("temporal", cases_dir=tmp_path)
