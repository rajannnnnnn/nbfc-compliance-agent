from datetime import date
from uuid import uuid4

from app.domain.documents import LoanAccountRef
from app.rules.base import FactIndex, FactRecord, NotApplicable
from app.rules.r01_docs_release_30d import R01DocsRelease30d


def _account(**kw) -> LoanAccountRef:
    defaults = dict(
        id=uuid4(),
        tenant_id=uuid4(),
        external_ref="LN-1",
        product_type="personal",
        is_microfinance=False,
        is_digital_lending=False,
        device_financed=False,
    )
    defaults.update(kw)
    return LoanAccountRef(**defaults)


def _facts(**field_dates) -> FactIndex:
    facts = {}
    for key, val in field_dates.items():
        if val is None:
            facts[key] = FactRecord(
                field_key=key, value_type=None, value_normalized=None, is_absent=True
            )
        elif isinstance(val, bool):
            facts[key] = FactRecord(
                field_key=key,
                value_type="boolean",
                value_normalized={"kind": "boolean", "v": val},
                is_absent=False,
            )
        else:
            facts[key] = FactRecord(
                field_key=key,
                value_type="date",
                value_normalized={"kind": "date", "v": val.isoformat()},
                is_absent=False,
            )
    return FactIndex(facts=facts)


def test_before_valid_from_not_applicable():
    rule = R01DocsRelease30d()
    facts = _facts(
        full_repayment_date=date(2025, 1, 1), original_docs_released_date=date(2025, 1, 15)
    )
    result = rule.evaluate(facts, _account(), as_of=date(2025, 6, 1), clause_excerpts={})
    assert isinstance(result, NotApplicable)


def test_exactly_29_days_compliant():
    rule = R01DocsRelease30d()
    repaid = date(2026, 1, 1)
    released = date(2026, 1, 30)  # 29 days
    facts = _facts(full_repayment_date=repaid, original_docs_released_date=released)
    result = rule.evaluate(
        facts, _account(), as_of=date(2026, 2, 1), clause_excerpts={"RBC2025/p35": "x"}
    )
    assert result.verdict == "compliant"


def test_exactly_30_days_compliant():
    rule = R01DocsRelease30d()
    repaid = date(2026, 1, 1)
    released = date(2026, 1, 31)  # 30 days
    facts = _facts(full_repayment_date=repaid, original_docs_released_date=released)
    result = rule.evaluate(facts, _account(), as_of=date(2026, 2, 1), clause_excerpts={})
    assert result.verdict == "compliant"


def test_31_days_violation():
    rule = R01DocsRelease30d()
    repaid = date(2026, 1, 1)
    released = date(2026, 2, 1)  # 31 days
    facts = _facts(full_repayment_date=repaid, original_docs_released_date=released)
    result = rule.evaluate(facts, _account(), as_of=date(2026, 3, 1), clause_excerpts={})
    assert result.verdict == "violation"
    assert "1 day(s)" in result.rationale


def test_docs_lost_flag_defers_to_r02b():
    rule = R01DocsRelease30d()
    facts = _facts(
        full_repayment_date=date(2026, 1, 1),
        original_docs_released_date=date(2026, 3, 1),
        docs_lost_flag=True,
    )
    result = rule.evaluate(facts, _account(), as_of=date(2026, 4, 1), clause_excerpts={})
    assert isinstance(result, NotApplicable)


def test_decisive_citation_present():
    rule = R01DocsRelease30d()
    facts = _facts(
        full_repayment_date=date(2026, 1, 1), original_docs_released_date=date(2026, 1, 20)
    )
    result = rule.evaluate(
        facts, _account(), as_of=date(2026, 2, 1), clause_excerpts={"RBC2025/p35": "text"}
    )
    assert result.citations[0].role == "decisive"
    assert result.citations[0].clause_path == "RBC2025/p35"
