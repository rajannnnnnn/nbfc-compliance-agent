"""M4-T03 follow-up: numeric-token recall against the real ingested corpus. LLD §8.3's own
claim is that lexical search "carries the numeric obligations" that embeddings frequently
miss — "thirty days", "Rs 5,000", "24 hours", "six months". This proves it against the real
`clause.tsv` column and real clause text, not a synthetic fixture.

Building this test surfaced two real gaps, fixed/documented rather than dodged:
1. `numeric_tokens`'s number-word list was missing "six", "four", "twenty-four", etc. — it
   only recognised {one, two, three, thirty, sixty, ninety}. Fixed in `app/retrieve/
   lexical.py` to a full one-to-ninety word list.
2. A *digit* token ("24") never matches a clause that spells the same number as *words*
   ("twenty-four") under `websearch_to_tsquery`, which has no numeral/word synonym
   dictionary — isolated and proven directly (bare "24" vs "twenty-four" against the real
   corpus) in `test_digit_form_does_not_recall_a_word_spelled_clause`, rather than silently
   choosing test values that avoid it. A real fix needs a synonym dictionary in the FTS
   configuration, tracked as follow-up; DL2025/p13 also uses "outside India" where a
   field label naturally says "offshore" — a vocabulary gap lexical search is not expected
   to close on its own, which is exactly why retrieval fuses it with vector search (LLD
   §8.4) rather than relying on lexical alone.
"""

from datetime import date

import pytest
from sqlalchemy import text as sqltext

from app.config import get_settings
from app.corpus.service import ingest
from app.db.engine import get_sessionmaker
from app.retrieve.lexical import build_lexical_query, fts_search, numeric_tokens

pytestmark = pytest.mark.integration


@pytest.fixture
async def snapshot_id():
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        await session.execute(sqltext("TRUNCATE corpus_snapshot CASCADE"))
        await session.commit()
    report = await ingest(settings=settings, activate=True)
    return report.snapshot_id


def test_numeric_tokens_extracts_digits_and_number_words():
    assert numeric_tokens("30 days") == ["30"]
    assert numeric_tokens("Rs 5,000 per day") == ["5,000"]
    assert numeric_tokens("thirty days") == ["thirty"]
    assert numeric_tokens("six months") == ["six"]
    assert numeric_tokens("no numbers here") == []


def test_build_lexical_query_appends_numeric_tokens_from_the_value():
    q = build_lexical_query("documents released", "30 days after repayment")
    assert q == "documents released 30"


@pytest.mark.parametrize(
    "field_label,value_summary,expected_clause_path",
    [
        ("Original documents released on", "30", "RBC2025/p35"),
        ("release delay compensation", "Rs 5,000 per day", "RBC2025/p39"),
        ("cooling-off period", "not less than one day", "DL2025/p10/note/1"),
        ("Recording retention period", "six months", "RBC-AMD2026/p100N"),
    ],
)
async def test_numeric_obligation_clause_is_a_top_lexical_hit(
    snapshot_id, field_label, value_summary, expected_clause_path
):
    settings = get_settings()
    sm = get_sessionmaker(settings)
    query = build_lexical_query(field_label, value_summary)
    assert numeric_tokens(value_summary), f"fixture bug: {value_summary!r} has no numeric token"

    async with sm() as session:
        candidates = await fts_search(
            session,
            snapshot_id=snapshot_id,
            entity_type="nbfc",
            borrower_class="general",
            as_of=date(2027, 1, 1),
            query=query,
            k=5,
        )

    paths = [c.clause_path for c in candidates]
    assert (
        expected_clause_path in paths
    ), f"query {query!r} did not surface {expected_clause_path} in top-5: {paths}"


async def test_digit_form_does_not_recall_a_word_spelled_clause(snapshot_id):
    """Documented gap, not a passing feature: DL2025/p13 spells its deadline as "twenty-four
    hours"; a bare digit-form query ("24") does not match it under `websearch_to_tsquery`,
    which has no numeral/word synonym dictionary, while the word-form query ("twenty-four")
    does. Isolated to the numeral alone (no other query terms) so the result is attributable
    to the digit/word mismatch specifically, not to an unrelated vocabulary gap (DL2025/p13
    also says "outside India" where a field label naturally says "offshore" — a separate,
    expected reason lexical search alone would miss it, which is why retrieval fuses lexical
    with vector search rather than relying on either alone). A real fix for the digit/word
    gap needs a synonym dictionary in the FTS configuration — tracked as follow-up."""
    settings = get_settings()
    sm = get_sessionmaker(settings)

    async with sm() as session:
        digit_hits = await fts_search(
            session,
            snapshot_id=snapshot_id,
            entity_type="nbfc",
            borrower_class="general",
            as_of=date(2027, 1, 1),
            query="24",
            k=5,
        )
        word_hits = await fts_search(
            session,
            snapshot_id=snapshot_id,
            entity_type="nbfc",
            borrower_class="general",
            as_of=date(2027, 1, 1),
            query="twenty-four",
            k=5,
        )

    assert "DL2025/p13" not in [c.clause_path for c in digit_hits]
    assert "DL2025/p13" in [c.clause_path for c in word_hits]
