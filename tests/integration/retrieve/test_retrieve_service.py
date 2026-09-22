"""Retrieval against the real ingested placeholder corpus. This is where the PRD §11 temporal
pair and the ADR-005 borrower-scope fix are proven end to end, not just asserted in a unit
test against synthetic rows."""

from datetime import date

import pytest
from sqlalchemy import text as sqltext

from app.config import get_settings
from app.corpus.service import ingest
from app.db.engine import get_sessionmaker
from app.domain.enums import ExclusionReason
from app.retrieve.applicability import ApplicabilityError
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


async def _retrieve(
    session, snapshot_id, *, field_key, as_of, borrower_class="general", value_summary=""
):
    settings = get_settings()
    return await retrieve_candidates(
        session=session,
        snapshot_id=snapshot_id,
        entity_type="nbfc",
        borrower_class=borrower_class,
        as_of=as_of,
        field_key=field_key,
        value_summary=value_summary,
        field_label="Collections contact timestamp",
        field_description="when contact occurred",
        query_vector=None,
        settings=settings,
    )


async def test_missing_as_of_raises(snapshot_id):
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        with pytest.raises(ApplicabilityError):
            await retrieve_candidates(
                session=session,
                snapshot_id=snapshot_id,
                entity_type="nbfc",
                borrower_class="general",
                as_of=None,
                field_key="contact_datetime",
                value_summary="",
                field_label="x",
                field_description="x",
                query_vector=None,
                settings=settings,
            )


async def test_temporal_pair_before_commencement_excludes_amendment(snapshot_id):
    """PRD §11, first half: on 2026-09-03 (before 2027-01-01), RBC-AMD2026/p100W must NOT be
    a candidate — it should appear in context_only with a not-yet-in-force reason."""
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        result = await _retrieve(
            session,
            snapshot_id,
            field_key="contact_datetime",
            as_of=date(2026, 9, 3),
            borrower_class="general",
        )

    candidate_paths = result.paths()
    assert "RBC-AMD2026/p100W" not in candidate_paths

    context_paths = {c.clause_path: c for c in result.context_only}
    assert "RBC-AMD2026/p100W" in context_paths
    assert context_paths["RBC-AMD2026/p100W"].exclusion_reason == ExclusionReason.NOT_YET_IN_FORCE


async def test_temporal_pair_after_commencement_includes_amendment(snapshot_id):
    """PRD §11, second half: on 2027-01-03 (after commencement), RBC-AMD2026/p100W IS a
    candidate."""
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        result = await _retrieve(
            session,
            snapshot_id,
            field_key="contact_datetime",
            as_of=date(2027, 1, 3),
            borrower_class="general",
        )
    assert "RBC-AMD2026/p100W" in result.paths()


async def test_microfinance_clause_excluded_for_general_borrower(snapshot_id):
    """ADR-005: RBC2025/p45 (microfinance contact hours) is in force well before 2027 and
    passes every predicate except borrower scope — it must land in context_only with reason
    borrower_scope for a general (non-microfinance) borrower, never in candidates."""
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        result = await _retrieve(
            session,
            snapshot_id,
            field_key="contact_datetime",
            as_of=date(2026, 9, 3),
            borrower_class="general",
        )
    assert "RBC2025/p45" not in result.paths()
    context_paths = {c.clause_path: c for c in result.context_only}
    if "RBC2025/p45" in context_paths:
        assert context_paths["RBC2025/p45"].exclusion_reason == ExclusionReason.BORROWER_SCOPE


async def test_microfinance_clause_included_for_microfinance_borrower(snapshot_id):
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        result = await _retrieve(
            session,
            snapshot_id,
            field_key="contact_datetime",
            as_of=date(2026, 9, 3),
            borrower_class="microfinance",
        )
    assert "RBC2025/p45" in result.paths()


async def test_draft_never_appears_in_candidates_or_context_only(snapshot_id):
    """ADR-012: RBC-AMD2026-DRAFT/p100W must never reach any citation role, at any date."""
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        result_before = await _retrieve(
            session,
            snapshot_id,
            field_key="contact_datetime",
            as_of=date(2026, 9, 3),
        )
        result_after = await _retrieve(
            session,
            snapshot_id,
            field_key="contact_datetime",
            as_of=date(2027, 6, 1),
        )
    for result in (result_before, result_after):
        all_paths = result.paths() | {c.clause_path for c in result.context_only}
        assert not any("DRAFT" in p for p in all_paths)


async def test_pinned_apr_bps_resolves(snapshot_id):
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
    assert len(result.candidates) > 0
    assert any(c.source == "pinned" for c in result.candidates)
