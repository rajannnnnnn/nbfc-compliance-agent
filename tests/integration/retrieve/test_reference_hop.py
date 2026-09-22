"""Reference-hop expansion, depth 1. M4-T06."""

from datetime import date

import pytest
from sqlalchemy import text as sqltext

from app.config import get_settings
from app.corpus.service import ingest
from app.db.engine import get_sessionmaker
from app.retrieve.service import retrieve_candidates

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


async def test_kfs_completeness_reaches_kfs_annex_via_incorporates_edge(snapshot_id):
    """apr_bps is pinned to DL2025/p8/i, which incorporates KFS2024 (the headline reference
    edge in the whole corpus, per LLD §6.5). Retrieval must follow that edge one hop and
    surface a KFS2024 clause, tagged source='reference_hop' — this is the mechanism that
    lets the system establish not just that a KFS was issued but whether it was complete."""
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        result = await retrieve_candidates(
            session=session,
            snapshot_id=snapshot_id,
            entity_type="nbfc",
            borrower_class="general",
            as_of=date(2026, 6, 1),
            field_key="apr_bps",
            value_summary="18.5%",
            field_label="Annual Percentage Rate",
            field_description="all-in cost of credit",
            query_vector=None,
            settings=settings,
        )
    hop_candidates = [c for c in result.candidates if c.source == "reference_hop"]
    assert (
        hop_candidates
    ), "expected at least one reference_hop candidate via DL2025/p8/i -> KFS2024"
    assert all(c.instrument_code == "KFS2024" for c in hop_candidates)
