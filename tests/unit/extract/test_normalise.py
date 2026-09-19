from datetime import date, time

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.extract.normalise import (
    NormalisationError,
    normalise_date,
    normalise_duration_days,
    normalise_money_to_paise,
    normalise_rate_to_bps,
    normalise_time,
)


def test_day_first_date():
    assert normalise_date("12/03/2026") == date(2026, 3, 12)


def test_day_first_date_with_dashes():
    assert normalise_date("12-03-2026") == date(2026, 3, 12)


def test_iso_date_accepted():
    assert normalise_date("2026-03-12") == date(2026, 3, 12)


def test_written_month_date():
    assert normalise_date("12 March 2026") == date(2026, 3, 12)


def test_malformed_date_raises():
    with pytest.raises(NormalisationError):
        normalise_date("not a date")


def test_money_with_indian_grouping():
    assert normalise_money_to_paise("₹1,20,000") == 12000000


def test_money_with_paise():
    assert normalise_money_to_paise("₹1,20,000.50") == 12000050


def test_money_plain_number():
    assert normalise_money_to_paise("5000") == 500000


def test_malformed_money_raises():
    with pytest.raises(NormalisationError):
        normalise_money_to_paise("a lot of money")


def test_rate_plain_percent():
    assert normalise_rate_to_bps("18.5%") == 1850


def test_rate_with_pa_qualifier():
    assert normalise_rate_to_bps("18.5% p.a.") == 1850


def test_rate_integer_percent():
    assert normalise_rate_to_bps("12%") == 1200


def test_time_24h():
    assert normalise_time("20:10") == time(20, 10)


def test_time_12h_pm():
    assert normalise_time("8:10 PM") == time(20, 10)


def test_time_12h_am():
    assert normalise_time("8:10 AM") == time(8, 10)


def test_duration_bare_days():
    assert normalise_duration_days("30") == 30


def test_duration_months():
    assert normalise_duration_days("6 months") == 180


def test_duration_years():
    assert normalise_duration_days("1 year") == 365


@given(
    rupees=st.integers(min_value=0, max_value=10_000_000),
    paise=st.integers(min_value=0, max_value=99),
)
def test_money_roundtrip_never_loses_precision(rupees, paise):
    raw = f"{rupees}.{paise:02d}"
    result = normalise_money_to_paise(raw)
    assert isinstance(result, int)
    assert result == rupees * 100 + paise


@given(bps=st.integers(min_value=0, max_value=100_000))
def test_rate_roundtrip_is_exact(bps):
    percent = bps / 100
    raw = f"{percent}%"
    result = normalise_rate_to_bps(raw)
    assert isinstance(result, int)
    assert result == bps
