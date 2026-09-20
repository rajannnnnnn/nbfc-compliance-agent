"""M6-T05/M7-T05 (eval harness): run_suite against the real stack for the three suites that
ship with real cases in this pass — numeric_rules, temporal, abstention. See
eval/loader.py's own docstring: the LLD §17.3 minimum suite sizes are not met here; this
proves the harness itself (loader, runner, metrics, persistence, report writing) is correct
against however many cases exist.
"""

import json

import pytest
from sqlalchemy import text as sqltext

from app.config import get_settings
from app.corpus.service import ingest
from app.db.engine import get_sessionmaker
from app.domain.verdicts import VerdictDraft
from app.llm.client import CallRecord, LLMClient
from app.schema.registry import FieldRegistry
from eval.harness import run_suite

pytestmark = pytest.mark.integration


def _stub_client(settings) -> LLMClient:
    """A deliberately dumb stub: always abstains with no citations. Good enough to prove the
    harness mechanics (persistence, metrics, report writing) work end to end; not meant to
    pass every case's exact citation expectations (e.g. EV-TEMPORAL-001's context citation),
    which requires real model judgement — that's the suite's actual job when pointed at a
    real model, not this test's."""
    client = LLMClient(settings)

    async def _structured(*, model_cls, model, messages, stage, adapter_id=None):
        draft = VerdictDraft(
            verdict="no_clause_found",
            citations=[],
            rationale="No candidate clause governs this fact.",
            confidence_band="medium",
        )
        record = CallRecord(
            provider="openai",
            model=model,
            adapter_id=adapter_id,
            stage=stage,
            tokens_in=5,
            tokens_out=5,
            wall_clock_ms=1,
            cost_usd=0.0,
            outcome="success",
        )
        return draft, record

    async def _embed(texts, *, model, dimensions):
        return [[0.001] * dimensions for _ in texts]

    client.structured = _structured  # type: ignore[method-assign]
    client.embed = _embed  # type: ignore[method-assign]
    return client


@pytest.fixture
async def snapshot_id():
    settings = get_settings()
    sm = get_sessionmaker(settings)
    async with sm() as session:
        await session.execute(sqltext("TRUNCATE corpus_snapshot CASCADE"))
        await session.commit()
    report = await ingest(settings=settings, activate=True)
    return report.snapshot_id


async def test_numeric_rules_suite_boundaries_are_exact(snapshot_id):
    """Boundary cases for all of the LLD §11's nine "pure date or money arithmetic" rules
    that this pass covers (R01, R02, R12, R13, R18, R22, R24) — deterministic, no model
    judgement involved, so this must be 100%. M5-T06 follow-up: extended beyond the tightest
    off-by-one boundary per rule with far-exceeding values, extreme low ends (zero-day/hour
    delays), and MissingFact code paths (a fact recorded as disclosed vs. never disclosed at
    all), so the suite exercises more than one arithmetic edge per rule. Also covers R02b
    (the lost-documents limb of R02, same RBC2025 §F arithmetic family: an extended 60-day
    window rather than R02's 30, plus its own not-assisted violation path) and, at LLD §17.3's
    own named boundary (18:59/19:00/19:01), R16 and R17's shared 08:00-19:00 contact window —
    R16 (RBC-AMD2026, post-2027 for any borrower) and R17 (RBC2025, pre-2027 for a
    microfinance borrower specifically) apply the identical window from different clauses,
    so both get their own boundary set. Also covers R23 (device-restriction preconditions:
    the 60-day past-due boundary, a below-minimum violation, a reversed-cure-notice-sequence
    violation, and an unfinanced-device violation — four independent precondition-failure
    paths) and R26 (KFS validity: the 3-working-day boundary, a below-minimum violation, a
    missing-proposal-number violation, and a missing-validity-period violation). Also covers
    R04 (APR-vs-rate-plus-fees computation, KFS2024/annexA/part1/9): the 200 bps tolerance
    boundary (200 compliant / 201 ambiguous — this check's own verdict for a diff beyond
    tolerance, not violation) plus a nonzero-fee case that exercises the fee-load
    annualisation arithmetic itself, not just the zero-fee shortcut. None of
    R02b/R04/R16/R17/R23/R26 is in the LLD's named list of nine, but all are the same kind of
    pure date/time/money/sequencing arithmetic."""
    settings = get_settings()
    sm = get_sessionmaker(settings)
    registry = FieldRegistry("app/schema/fields.yaml")
    client = _stub_client(settings)

    async with sm() as session:
        report = await run_suite(
            "numeric_rules",
            session=session,
            snapshot_id=snapshot_id,
            settings=settings,
            registry=registry,
            client=client,
        )

    assert report["case_count"] == 49
    assert report["metrics"]["verdict_accuracy"] == 1.0
    assert report["metrics"]["hallucinated_citation_rate"] == 0.0
    assert all(r["passed"] for r in report["results"])


async def test_abstention_suite_correctly_abstains(snapshot_id):
    """40 cases (up from 2) — the LLD §17.3 minimum for this suite, the first one this build
    reaches. 37 cover every field in `app/schema/fields.yaml` that no registered rule
    consumes (checked directly with `app.rules.registry.all_rules()`, not assumed), each a
    real abstention scenario since no rule can fire and no clause in the ingested corpus
    governs the field directly. 3 more vary doc_type/account_profile/value on fields that
    are declared against more than one doc_type, still genuinely distinct scenarios rather
    than a repeated case."""
    settings = get_settings()
    sm = get_sessionmaker(settings)
    registry = FieldRegistry("app/schema/fields.yaml")
    client = _stub_client(settings)

    async with sm() as session:
        report = await run_suite(
            "abstention",
            session=session,
            snapshot_id=snapshot_id,
            settings=settings,
            registry=registry,
            client=client,
        )

    assert report["case_count"] == 40
    assert report["metrics"]["abstention_correctness"] == 1.0
    assert report["metrics"]["hallucinated_citation_rate"] == 0.0


async def test_temporal_suite_verdicts_correct_even_with_a_dumb_stub(snapshot_id):
    """PRD §11 temporal pair as a first-class eval case, plus five more pairs added across
    this pass: three across the 2027-01-01 RBC-AMD2026 commencement date (R18 recording
    retention, R22 prior-visit intimation, R24 restoration compensation), and two across
    DL2025's own 2025-05-08 phased commencement date (R13 offshore deletion, R12 grievance
    escalation disclosure) — closing part of the "no 2025 phased-date coverage" gap noted in
    TASKS.md M5-T06. The *verdict* on both sides of each commencement date is correct
    regardless of model quality (one side is a rule-level fact or corpus-applicability fact,
    never a model judgement call) — only the citation on the abstention side depends on model
    judgement, which this dumb stub doesn't attempt."""
    settings = get_settings()
    sm = get_sessionmaker(settings)
    registry = FieldRegistry("app/schema/fields.yaml")
    client = _stub_client(settings)

    async with sm() as session:
        report = await run_suite(
            "temporal",
            session=session,
            snapshot_id=snapshot_id,
            settings=settings,
            registry=registry,
            client=client,
        )

    assert report["case_count"] == 12
    by_ref = {r["case_ref"]: r for r in report["results"]}
    for before_ref, after_ref in [
        ("EV-TEMPORAL-001", "EV-TEMPORAL-002"),
        ("EV-TEMPORAL-003", "EV-TEMPORAL-004"),
        ("EV-TEMPORAL-005", "EV-TEMPORAL-006"),
        ("EV-TEMPORAL-007", "EV-TEMPORAL-008"),
        ("EV-TEMPORAL-009", "EV-TEMPORAL-010"),
        ("EV-TEMPORAL-011", "EV-TEMPORAL-012"),
    ]:
        assert "verdict" not in by_ref[before_ref]["diff"]  # no_clause_found, correct
        assert by_ref[after_ref]["passed"]  # violation, decisive citation from the rule
    assert report["metrics"]["hallucinated_citation_rate"] == 0.0


async def test_run_persists_eval_run_and_eval_result_rows(snapshot_id):
    settings = get_settings()
    sm = get_sessionmaker(settings)
    registry = FieldRegistry("app/schema/fields.yaml")
    client = _stub_client(settings)

    async with sm() as session:
        report = await run_suite(
            "abstention",
            session=session,
            snapshot_id=snapshot_id,
            settings=settings,
            registry=registry,
            client=client,
        )

    async with sm() as session:
        run_row = (
            await session.execute(
                sqltext("SELECT case_count, suite, metrics FROM eval_run WHERE id = :id"),
                {"id": report["eval_run_id"]},
            )
        ).first()
        assert run_row is not None
        assert run_row.suite == "abstention"
        assert run_row.case_count == 40
        stored_metrics = (
            json.loads(run_row.metrics) if isinstance(run_row.metrics, str) else run_row.metrics
        )
        assert stored_metrics["abstention_correctness"] == 1.0

        result_count = (
            await session.execute(
                sqltext("SELECT COUNT(*) FROM eval_result WHERE eval_run_id = :id"),
                {"id": report["eval_run_id"]},
            )
        ).scalar_one()
        assert result_count == 40


async def test_run_writes_a_report_file(snapshot_id, tmp_path, monkeypatch):
    import eval.harness as harness_module

    monkeypatch.setattr(harness_module, "REPORTS_DIR", tmp_path)
    settings = get_settings()
    sm = get_sessionmaker(settings)
    registry = FieldRegistry("app/schema/fields.yaml")
    client = _stub_client(settings)

    async with sm() as session:
        await run_suite(
            "abstention",
            session=session,
            snapshot_id=snapshot_id,
            settings=settings,
            registry=registry,
            client=client,
        )

    latest = tmp_path / "eval_abstention_latest.json"
    assert latest.exists()
    body = json.loads(latest.read_text())
    assert body["suite"] == "abstention"


async def test_unknown_suite_raises():
    from eval.harness import run_suite as _rs

    with pytest.raises(FileNotFoundError, match="not_a_real_suite"):
        await _rs(
            "not_a_real_suite",
            session=None,  # never reached — load_suite fails first
            snapshot_id=None,
            settings=get_settings(),
            registry=FieldRegistry("app/schema/fields.yaml"),
            client=None,
        )
