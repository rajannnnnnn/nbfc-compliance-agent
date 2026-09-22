from app.extract.spans import build_span, truncate_longest_first, verify_span


def test_span_found_is_verified():
    assert verify_span("thirty days", "released within thirty days of repayment") is True


def test_span_absent_is_not_verified():
    assert verify_span("sixty days", "released within thirty days of repayment") is False


def test_build_span_sets_verified_flag():
    source = "released within thirty days of repayment"
    span = build_span(20, 31, "thirty days", source)
    assert span.verified is True


def test_build_span_unverified_for_fabricated_quote():
    source = "released within thirty days of repayment"
    span = build_span(0, 10, "fabricated quote not in source", source)
    assert span.verified is False


def test_truncate_longest_first_picks_the_biggest():
    spans = [("a", 10), ("b", 100), ("c", 50)]
    result = truncate_longest_first(spans, budget_remaining=60)
    # total=160, need to drop until <=60: drop b(100)->60 remaining total=60, done
    assert result == ["b"]


def test_truncate_longest_first_empty_when_within_budget():
    spans = [("a", 10), ("b", 20)]
    result = truncate_longest_first(spans, budget_remaining=100)
    assert result == []
