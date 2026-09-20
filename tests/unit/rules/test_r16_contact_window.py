from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.domain.documents import LoanAccountRef
from app.rules.base import FactIndex, FactRecord, NotApplicable
from app.rules.r16_contact_window import R16ContactWindow

_IST = ZoneInfo("Asia/Kolkata")


def _account() -> LoanAccountRef:
    return LoanAccountRef(
        id=uuid4(),
        tenant_id=uuid4(),
        external_ref="LN-1",
        product_type="personal",
        is_microfinance=False,
        is_digital_lending=False,
        device_financed=False,
    )


def _facts_at(dt: datetime) -> FactIndex:
    return FactIndex(
        facts={
            "contact_datetime": FactRecord(
                field_key="contact_datetime",
                value_type="datetime",
                value_normalized={"kind": "datetime", "v": dt.isoformat()},
                is_absent=False,
            )
        }
    )


def test_before_2027_not_applicable():
    rule = R16ContactWindow()
    dt = datetime(2026, 9, 3, 20, 10, tzinfo=_IST)
    result = rule.evaluate(_facts_at(dt), _account(), as_of=date(2026, 9, 3), clause_excerpts={})
    assert isinstance(result, NotApplicable)


def test_0759_violation():
    rule = R16ContactWindow()
    dt = datetime(2027, 1, 3, 7, 59, tzinfo=_IST)
    result = rule.evaluate(_facts_at(dt), _account(), as_of=date(2027, 1, 3), clause_excerpts={})
    assert result.verdict == "violation"


def test_0800_compliant():
    rule = R16ContactWindow()
    dt = datetime(2027, 1, 3, 8, 0, tzinfo=_IST)
    result = rule.evaluate(_facts_at(dt), _account(), as_of=date(2027, 1, 3), clause_excerpts={})
    assert result.verdict == "compliant"


def test_1859_compliant():
    rule = R16ContactWindow()
    dt = datetime(2027, 1, 3, 18, 59, tzinfo=_IST)
    result = rule.evaluate(_facts_at(dt), _account(), as_of=date(2027, 1, 3), clause_excerpts={})
    assert result.verdict == "compliant"


def test_1900_compliant_per_adr014():
    rule = R16ContactWindow()
    dt = datetime(2027, 1, 3, 19, 0, tzinfo=_IST)
    result = rule.evaluate(_facts_at(dt), _account(), as_of=date(2027, 1, 3), clause_excerpts={})
    assert result.verdict == "compliant"


def test_1901_violation():
    rule = R16ContactWindow()
    dt = datetime(2027, 1, 3, 19, 1, tzinfo=_IST)
    result = rule.evaluate(_facts_at(dt), _account(), as_of=date(2027, 1, 3), clause_excerpts={})
    assert result.verdict == "violation"


def test_utc_stored_timestamp_correctly_converted_to_ist():
    """ADR-014's own regression: a UTC-tagged 14:40 is 20:10 IST — must read as a violation,
    not silently pass as compliant because .timetz() would have used UTC directly."""
    rule = R16ContactWindow()
    dt_utc = datetime(2027, 1, 3, 14, 40, tzinfo=ZoneInfo("UTC"))  # == 20:10 IST
    result = rule.evaluate(
        _facts_at(dt_utc), _account(), as_of=date(2027, 1, 3), clause_excerpts={}
    )
    assert result.verdict == "violation"
    assert "20:10" in result.rationale


def test_temporal_pair_second_half_matches_prd_example():
    """The same 20:10 call, 2027-01-03: PRD §11 requires a decisive violation citation."""
    rule = R16ContactWindow()
    dt = datetime(2027, 1, 3, 20, 10, tzinfo=_IST)
    result = rule.evaluate(
        _facts_at(dt),
        _account(),
        as_of=date(2027, 1, 3),
        clause_excerpts={"RBC-AMD2026/p100W": "text"},
    )
    assert result.verdict == "violation"
    assert result.citations[0].role == "decisive"
    assert result.citations[0].clause_path == "RBC-AMD2026/p100W"
