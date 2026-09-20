"""End-to-end corpus ingest against real Postgres, against the placeholder corpus (ADR-001).
M1-T08 (snapshot), M1-T09 (verify), M1-T12 (pinning)."""

import pytest
from sqlalchemy import text as sqltext

import app.corpus.service as corpus_service
from app.config import get_settings
from app.corpus.pinning import PinningMismatchError, load_and_validate
from app.corpus.service import ingest
from app.db.engine import get_sessionmaker

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _clean_corpus():
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        await session.execute(sqltext("TRUNCATE corpus_snapshot CASCADE"))
        await session.commit()
    yield


async def test_ingest_writes_snapshot_and_all_five_instruments():
    settings = get_settings()
    report = await ingest(settings=settings, activate=True)
    assert report.chunk_count > 0
    codes = {i.code for i in report.instruments}
    assert codes == {"DL2025", "KFS2024", "RBC2025", "RBC-AMD2026", "RBC-AMD2026-DRAFT"}


async def test_incorporates_edge_present():
    report = await ingest(settings=get_settings(), activate=True)
    assert any(
        e["from"] == "DL2025/p8/i"
        and e["to_instrument"] == "KFS2024"
        and e["kind"] == "incorporates"
        for e in report.reference_edges
    )


async def test_activation_leaves_exactly_one_active_snapshot():
    settings = get_settings()
    await ingest(settings=settings, activate=True)
    await ingest(settings=settings, activate=True)  # second ingest, re-activates
    sm = get_sessionmaker(settings)
    async with sm() as session:
        row = await session.execute(
            sqltext("SELECT count(*) FROM corpus_snapshot WHERE is_active = true")
        )
        assert row.scalar_one() == 1
        row = await session.execute(sqltext("SELECT count(*) FROM corpus_snapshot"))
        assert row.scalar_one() == 2  # both retained, only one active


async def test_draft_instrument_not_citable():
    settings = get_settings()
    await ingest(settings=settings, activate=True)
    sm = get_sessionmaker(settings)
    async with sm() as session:
        row = await session.execute(
            sqltext(
                "SELECT citable, status FROM regulation_instrument "
                "WHERE code = 'RBC-AMD2026-DRAFT' AND snapshot_id = "
                "(SELECT id FROM corpus_snapshot WHERE is_active = true)"
            )
        )
        citable, status = row.one()
        assert citable is False
        assert status == "draft"


async def test_amendment_instrument_is_secondary_sourced():
    settings = get_settings()
    await ingest(settings=settings, activate=True)
    sm = get_sessionmaker(settings)
    async with sm() as session:
        row = await session.execute(
            sqltext(
                "SELECT verification_status FROM regulation_instrument "
                "WHERE code = 'RBC-AMD2026' AND snapshot_id = "
                "(SELECT id FROM corpus_snapshot WHERE is_active = true)"
            )
        )
        assert row.scalar_one() == "secondary_sourced"


async def test_para_overrides_applied_to_dl2025_p6_and_p17():
    settings = get_settings()
    await ingest(settings=settings, activate=True)
    sm = get_sessionmaker(settings)
    async with sm() as session:
        row = await session.execute(
            sqltext(
                "SELECT clause_path, effective_from FROM clause "
                "WHERE instrument_code = 'DL2025' AND clause_path IN ('DL2025/p6', 'DL2025/p17') "
                "AND snapshot_id = (SELECT id FROM corpus_snapshot WHERE is_active = true)"
            )
        )
        by_path = {r[0]: r[1] for r in row}
        assert str(by_path["DL2025/p6"]) == "2025-11-01"
        assert str(by_path["DL2025/p17"]) == "2025-06-15"


async def test_all_pinned_paths_resolve_against_placeholder_corpus():
    settings = get_settings()
    report = await ingest(settings=settings, activate=True)
    sm = get_sessionmaker(settings)
    async with sm() as session:
        pins = await load_and_validate(
            report.snapshot_id, session, pinning_path="app/corpus/pinning.yaml"
        )
        assert len(pins) > 0


async def test_pinning_mismatch_names_every_missing_path(tmp_path):
    settings = get_settings()
    report = await ingest(settings=settings, activate=True)
    bad_pinning = tmp_path / "pinning.yaml"
    bad_pinning.write_text(
        "version: 1\npins:\n  x: ['DL2025/p999', 'DL2025/p998']\n  y: ['RBC2025/pDOESNOTEXIST']\n"
    )
    sm = get_sessionmaker(settings)
    async with sm() as session:
        with pytest.raises(PinningMismatchError) as exc_info:
            await load_and_validate(report.snapshot_id, session, pinning_path=str(bad_pinning))
    msg = str(exc_info.value)
    assert "DL2025/p999" in msg
    assert "DL2025/p998" in msg
    assert "RBC2025/pDOESNOTEXIST" in msg


async def test_ingest_stores_real_vector_embeddings_when_api_key_set(monkeypatch):
    """Regression for a real bug found live (docs/DECISIONS.md ADR-048): the raw INSERT bound
    a bare Python list to pgvector's `vector` column, which asyncpg rejects outright
    ("expected str, got list"). No live embedding call here — `embed_texts` is stubbed so
    this exercises only the insert/CAST path, not the API."""

    async def _fake_embed_texts(texts, *, client, settings):
        return [[0.1] * settings.embedding_dimension for _ in texts]

    monkeypatch.setattr(corpus_service, "embed_texts", _fake_embed_texts)

    settings = get_settings().model_copy(update={"embedding_api_key": "test-key-not-real"})
    await ingest(settings=settings, activate=True)

    sm = get_sessionmaker(settings)
    async with sm() as session:
        rows = await session.execute(
            sqltext(
                "SELECT count(*) FROM clause "
                "WHERE snapshot_id = (SELECT id FROM corpus_snapshot WHERE is_active = true) "
                "AND embedding IS NOT NULL"
            )
        )
        total = await session.execute(
            sqltext(
                "SELECT count(*) FROM clause "
                "WHERE snapshot_id = (SELECT id FROM corpus_snapshot WHERE is_active = true)"
            )
        )
        assert rows.scalar_one() == total.scalar_one() > 0


async def test_no_decimal_clause_paths_anywhere(tmp_path):
    """CLAUDE.md §2.6: RBI instruments in this family do not use decimal numbering. A path
    like 'DL2025/Ch.IV/4.2(a)' must never appear."""
    import re

    settings = get_settings()
    await ingest(settings=settings, activate=True)
    sm = get_sessionmaker(settings)
    async with sm() as session:
        rows = await session.execute(
            sqltext(
                "SELECT clause_path FROM clause WHERE snapshot_id = (SELECT id FROM corpus_snapshot WHERE is_active = true)"
            )
        )
        pattern = re.compile(r"^[A-Za-z0-9-]+/(p[0-9]+[A-Za-z]?|annex[A-Za-z])(/[^/]+){0,2}$")
        for (path,) in rows:
            assert pattern.match(path), f"clause path does not match canonical format: {path}"
