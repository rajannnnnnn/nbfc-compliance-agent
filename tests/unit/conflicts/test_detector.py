from datetime import date

import pytest

from app.conflicts.detector import ConflictComparisonError, compare
from app.domain.facts import BoolValue, DateValue, MoneyValue, RateValue


def test_equal_matching_returns_true():
    assert compare("equal", RateValue(bps=1850), RateValue(bps=1850), {}) is True


def test_equal_mismatch_returns_false():
    assert compare("equal", RateValue(bps=1850), RateValue(bps=1900), {}) is False


def test_equal_within_tolerance_ok():
    assert compare("equal_within", RateValue(bps=1850), RateValue(bps=1851), {"tolerance": 1})


def test_equal_within_tolerance_breach():
    assert not compare("equal_within", RateValue(bps=1850), RateValue(bps=1900), {"tolerance": 1})


def test_equal_within_rejects_non_numeric_kind():
    with pytest.raises(ConflictComparisonError):
        compare("equal_within", BoolValue(v=True), BoolValue(v=False), {"tolerance": 1})


def test_date_order_after_within_days_ok():
    a = DateValue(v=date(2026, 3, 2))
    b = DateValue(v=date(2026, 4, 1))  # 30 days later
    assert compare("date_order", a, b, {"direction": "after", "within_days": 30})


def test_date_order_after_within_days_breach():
    a = DateValue(v=date(2026, 3, 2))
    b = DateValue(v=date(2026, 4, 12))  # 41 days later
    assert not compare("date_order", a, b, {"direction": "after", "within_days": 30})


def test_date_order_after_requires_strictly_after():
    a = DateValue(v=date(2026, 3, 2))
    b = DateValue(v=date(2026, 3, 2))
    assert not compare("date_order", a, b, {"direction": "after"})


def test_date_order_before():
    a = DateValue(v=date(2026, 4, 1))
    b = DateValue(v=date(2026, 3, 1))
    assert compare("date_order", a, b, {"direction": "before"})


def test_kind_mismatch_raises():
    with pytest.raises(ConflictComparisonError):
        compare("equal", MoneyValue(paise=100), RateValue(bps=100), {})


def test_unknown_operator_raises():
    with pytest.raises(ConflictComparisonError):
        compare("bogus_op", RateValue(bps=1), RateValue(bps=1), {})


def test_date_order_strictly_increasing_direction_not_pairwise():
    """strictly_increasing needs the whole chain (>2 members) — compare() itself only handles
    a pair and refuses this direction, forcing callers through the chain-aware path in
    detector.py's _evaluate_strictly_increasing_group."""
    a = DateValue(v=date(2026, 1, 1))
    b = DateValue(v=date(2026, 1, 2))
    with pytest.raises(ConflictComparisonError):
        compare("date_order", a, b, {"direction": "strictly_increasing"})
