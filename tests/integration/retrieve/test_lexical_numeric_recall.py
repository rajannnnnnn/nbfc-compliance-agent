"""M4-T03 follow-up: numeric-token recall against the real ingested corpus. LLD §8.3's own
claim is that lexical search "carries the numeric obligations" that embeddings frequently
miss — "thirty days", "Rs 5,000", "24 hours", "six months". This proves it against the real
`clause.tsv` column and real clause text, not a synthetic fixture.

Building this test surfaced two real gaps, fixed/documented rather than dodged:
1. `numeric_tokens`'s number-word list was missing "six", "four", "twenty-four", etc. — it
   only recognised {one, two, three, thirty, sixty, ninety}. Fixed in `app/retrieve/
   lexical.py` to a full one-to-ninety word list.
2. A *digit* token ("24") never matched a clause that spelled the same number as *words*
   ("twenty-four") under bare `websearch_to_tsquery('english', ...)` — isolated and proven
   directly (bare "24" vs "twenty-four" against the real corpus). Fixed in M4-T03b
   (docs/DECISIONS.md ADR-037) with a `numbers_syn` synonym dictionary and a `clausecheck_en`
   text search configuration (migration 0010) that both `clause.tsv` and this module's
   queries now use; `test_digit_form_recalls_a_word_spelled_clause` proves both spellings
   recall `DL2025/p13`. DL2025/p13 also uses "outside India" where a field label naturally
   says "offshore" — a vocabulary gap lexical search is not expected to close on its own,
   which is exactly why retrieval fuses it with vector search (LLD §8.4) rather than relying
   on lexical alone.
"""

from datetime import date

import pytest
from sqlalchemy import text as sqltext

from app.config import get_settings
from app.corpus.service import ingest
from app.db.engine import get_sessionmaker
from app.retrieve import lexical
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


async def test_resolve_ts_config_falls_back_without_raising_when_config_is_absent():
    """Regression for the production incident where fts_search hardcoded
    'clausecheck_en' and crashed every single lexical call on managed Postgres
    (Neon, RDS, ...), which lacks filesystem access to install the
    numbers_syn synonym dictionary migration 0010 needs — confirmed via a real
    production traceback (asyncpg.exceptions.UndefinedObjectError: text search
    configuration "clausecheck_en" does not exist). resolve_ts_config must
    mirror migration 0010's own fallback (plain 'english') instead of assuming
    the custom config exists."""
    settings = get_settings()
    sm = get_sessionmaker(settings)

    # Whatever this Postgres actually has, the existence lookup itself must never raise —
    # querying pg_ts_config for a name that isn't there is a normal empty result, not an
    # error (unlike asking websearch_to_tsquery for a config Postgres doesn't have).
    async with sm() as session:
        lexical._resolved_ts_config = None
        row = (
            await session.execute(
                sqltext(lexical._TS_CONFIG_EXISTS_SQL), {"cfg": "definitely_does_not_exist_xyz"}
            )
        ).first()
        assert row is None

    # The result is cached — resolve it once for real, then confirm the cache is used
    # rather than re-querying, and that whichever value comes back is a real, usable
    # regconfig name (never raises when bound into websearch_to_tsquery).
    lexical._resolved_ts_config = None
    async with sm() as session:
        cfg = await lexical.resolve_ts_config(session)
    assert cfg in ("clausecheck_en", "english")
    assert lexical._resolved_ts_config == cfg

    async with sm() as session:
        result = await session.execute(
            sqltext("SELECT websearch_to_tsquery(CAST(:tscfg AS regconfig), :q)::text AS tq"),
            {"tscfg": cfg, "q": "thirty days"},
        )
        assert result.first().tq  # did not raise, produced a real tsquery


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


async def test_digit_form_recalls_a_word_spelled_clause(snapshot_id):
    """M4-T03b (docs/DECISIONS.md ADR-037): DL2025/p13 spells its deadline as "twenty-four
    hours"; a bare digit-form query ("24") now matches it too, because `clause.tsv` and this
    query both use the `clausecheck_en` text search configuration, which folds digit and word
    forms of the same number to the same token via a synonym dictionary before stemming.
    Isolated to the numeral alone (no other query terms) so the result is attributable to the
    digit/word fix specifically, not to an unrelated vocabulary gap (DL2025/p13 also says
    "outside India" where a field label naturally says "offshore" — a separate, expected
    reason lexical search alone would miss it, which is why retrieval fuses lexical with
    vector search rather than relying on either alone)."""
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

    assert "DL2025/p13" in [c.clause_path for c in digit_hits]
    assert "DL2025/p13" in [c.clause_path for c in word_hits]
