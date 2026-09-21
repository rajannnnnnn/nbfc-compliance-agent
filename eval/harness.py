"""run_suite(...). LLD §17.4. `python -m eval.harness --suite <name>` is `make eval`'s entry
point; `--report-latest` is `make eval-report`'s."""

import argparse
import asyncio
import json
import subprocess
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.config import Settings, get_settings
from app.corpus.snapshot import get_active_snapshot_id
from app.db.engine import get_sessionmaker
from app.llm.client import LLMClient, PermanentLLMError, TransientLLMError
from app.schema.registry import FieldRegistry
from eval.loader import load_suite
from eval.metrics import (
    compute_conflict_metrics,
    compute_end_to_end_metrics,
    compute_extraction_metrics,
    compute_verdict_metrics,
)
from eval.runner import (
    ExtractionOutcome,
    run_case,
    run_conflict_case,
    run_end_to_end_case,
    run_extraction_case,
)

REPORTS_DIR = Path("reports")


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


async def run_suite(
    suite: str,
    *,
    session: AsyncSession,
    snapshot_id: UUID,
    settings: Settings,
    registry: FieldRegistry,
    client: LLMClient,
) -> dict[str, Any]:
    cases = load_suite(suite)
    if not cases:
        raise ValueError(f"suite {suite!r} has zero cases in eval/cases/{suite}/")

    stages = {c.stage for c in cases}
    if len(stages) != 1:
        raise ValueError(f"suite {suite!r} mixes stages {stages!r} — one suite, one stage")
    stage = stages.pop()

    started_at = datetime.now(UTC)
    outcomes: list[Any] = []
    if stage == "extraction":
        errored_cases: list[dict[str, str]] = []
        for case in cases:
            try:
                outcome = await run_extraction_case(
                    session,
                    case,
                    settings=settings,
                    registry=registry,
                    client=client,
                )
            except (TransientLLMError, PermanentLLMError) as exc:
                # A real provider-side failure on one case (e.g. ADR-041: Gemini's
                # structured-output mode rejecting a large per-doc-type schema outright)
                # must not lose every other case's real results — recorded honestly as a
                # zero-field, failed outcome and excluded from field-level metrics (never
                # counted as a false success), not silently swallowed or faked as passing.
                outcome = ExtractionOutcome(
                    case_ref=case.case_ref, fields=[], passed=False, diff={"error": str(exc)}
                )
                errored_cases.append({"case_ref": case.case_ref, "error": str(exc)})
            outcomes.append(outcome)
        metrics_source = [o for o in outcomes if o.fields]
        if not metrics_source:
            raise RuntimeError(f"suite {suite!r}: every case errored before producing a field")
        metrics: Any = compute_extraction_metrics(metrics_source)
    elif suite == "conflicts":
        # LLD §17.3: the `conflicts` suite runs at stage "end_to_end" — the same stage name
        # the (still-empty) `end_to_end` suite itself will use, so dispatch here keys off the
        # suite, not the stage, to avoid the two colliding once end_to_end cases exist. This
        # only implements the cross-document conflict-detection half of "end_to_end"
        # (deterministic, no LLM call — app/conflicts/detector.py) via run_conflict_case; a
        # suite genuinely covering full account compliance state end to end is a distinct,
        # larger runner not yet built (see ADR-051).
        for case in cases:
            outcome = await run_conflict_case(session, case, settings=settings, registry=registry)
            outcomes.append(outcome)
        metrics = compute_conflict_metrics(cases, outcomes)
    elif suite == "end_to_end":
        for case in cases:
            outcome = await run_end_to_end_case(
                session,
                case,
                snapshot_id=snapshot_id,
                settings=settings,
                registry=registry,
                client=client,
            )
            outcomes.append(outcome)
        metrics = compute_end_to_end_metrics(outcomes)
    else:
        for case in cases:
            outcome = await run_case(
                session,
                case,
                snapshot_id=snapshot_id,
                settings=settings,
                registry=registry,
                client=client,
            )
            outcomes.append(outcome)
        metrics = compute_verdict_metrics(cases, outcomes)
    finished_at = datetime.now(UTC)

    eval_run_id = uuid7()
    await session.execute(
        text("""
            INSERT INTO eval_run
                (id, started_at, finished_at, git_sha, corpus_snapshot_id, model_config,
                 serving_mode, suite, case_count, metrics)
            VALUES
                (:id, :started, :finished, :sha, :snapshot_id, CAST(:model_config AS jsonb),
                 :serving_mode, :suite, :case_count, CAST(:metrics AS jsonb))
            """),
        {
            "id": str(eval_run_id),
            "started": started_at,
            "finished": finished_at,
            "sha": _git_sha(),
            "snapshot_id": str(snapshot_id),
            "model_config": json.dumps(
                {"verdict_model": settings.verdict_model, "extract_model": settings.extract_model}
            ),
            "serving_mode": settings.serving_mode,
            "suite": suite,
            "case_count": len(cases),
            "metrics": json.dumps(asdict(metrics)),
        },
    )

    for case, outcome in zip(cases, outcomes, strict=True):
        eval_case_row = await session.execute(
            text("""
                INSERT INTO eval_case
                    (id, case_ref, suite, stage, doc_type, input_ref, event_date,
                     account_profile, expected, tolerance, is_adversarial, notes)
                VALUES
                    (:id, :ref, :suite, :stage, :doc_type, :input_ref, :event_date,
                     CAST(:profile AS jsonb), CAST(:expected AS jsonb), CAST(:tolerance AS jsonb),
                     :adversarial, :notes)
                ON CONFLICT (case_ref) DO UPDATE SET
                    expected = EXCLUDED.expected, tolerance = EXCLUDED.tolerance
                RETURNING id
                """),
            {
                "id": str(uuid7()),
                "ref": case.case_ref,
                "suite": case.suite,
                "stage": case.stage,
                "doc_type": case.doc_type,
                "input_ref": case.input_ref or "",
                "event_date": date.fromisoformat(case.event_date),
                "profile": case.account_profile.model_dump_json(),
                "expected": case.expected.model_dump_json(),
                "tolerance": json.dumps(case.tolerance),
                "adversarial": case.is_adversarial,
                "notes": case.notes,
            },
        )
        eval_case_id = eval_case_row.scalar_one()

        if stage == "extraction":
            actual_payload = {
                "fields": [
                    {
                        "field_key": fo.field_key,
                        "expected_present": fo.expected_present,
                        "actual_present": fo.actual_present,
                        "value_match": fo.value_match,
                        "span_verified": fo.span_verified,
                    }
                    for fo in outcome.fields
                ]
            }
        elif suite == "conflicts":
            actual_payload = {
                "conflict_detected": outcome.conflict_detected,
                "raises_checks": outcome.raises_checks,
            }
        elif suite == "end_to_end":
            actual_payload = {"state": outcome.state}
        else:
            actual_payload = {
                "verdict": outcome.verdict,
                "check_key": outcome.check_key,
                "decisive_citations": outcome.decisive_citations,
                "context_citations": outcome.context_citations,
            }

        await session.execute(
            text("""
                INSERT INTO eval_result (id, eval_run_id, eval_case_id, passed, actual, diff)
                VALUES (:id, :run_id, :case_id, :passed, CAST(:actual AS jsonb), CAST(:diff AS jsonb))
                """),
            {
                "id": str(uuid7()),
                "run_id": str(eval_run_id),
                "case_id": str(eval_case_id),
                "passed": outcome.passed,
                "actual": json.dumps(actual_payload),
                "diff": json.dumps(outcome.diff),
            },
        )
    await session.commit()

    report = {
        "eval_run_id": str(eval_run_id),
        "suite": suite,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "git_sha": _git_sha(),
        "case_count": len(cases),
        "metrics": asdict(metrics),
        "results": [
            {"case_ref": c.case_ref, "passed": o.passed, "diff": o.diff}
            for c, o in zip(cases, outcomes, strict=True)
        ],
    }
    if stage == "extraction" and errored_cases:
        report["errored_cases"] = errored_cases
    REPORTS_DIR.mkdir(exist_ok=True)
    ts = started_at.strftime("%Y%m%dT%H%M%SZ")
    report_path = REPORTS_DIR / f"eval_{suite}_{ts}.json"
    report_path.write_text(json.dumps(report, indent=2))
    latest_path = REPORTS_DIR / f"eval_{suite}_latest.json"
    latest_path.write_text(json.dumps(report, indent=2))

    return report


async def _cli_run_suite(suite: str) -> dict[str, Any]:
    settings = get_settings()
    sessionmaker = get_sessionmaker(settings)
    registry = FieldRegistry("app/schema/fields.yaml")
    client = LLMClient(settings)
    async with sessionmaker() as session:
        snapshot_id = await get_active_snapshot_id(session)
        if snapshot_id is None:
            raise SystemExit("no active corpus snapshot — run `make ingest` first")
        return await run_suite(
            suite,
            session=session,
            snapshot_id=snapshot_id,
            settings=settings,
            registry=registry,
            client=client,
        )


def _report_latest() -> None:
    latest_files = sorted(REPORTS_DIR.glob("eval_*_latest.json"))
    if not latest_files:
        print("no eval reports found in reports/")
        return
    for path in latest_files:
        body = json.loads(path.read_text())
        print(f"## {body['suite']} ({body['case_count']} cases, {body['git_sha'][:8]})")
        for name, value in body["metrics"].items():
            if name != "case_count":
                print(f"- {name}: {value}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite")
    parser.add_argument("--report-latest", action="store_true")
    args = parser.parse_args()

    if args.report_latest:
        _report_latest()
        return
    if not args.suite:
        raise SystemExit("--suite is required unless --report-latest is passed")

    report = asyncio.run(_cli_run_suite(args.suite))
    print(json.dumps(report["metrics"], indent=2))


if __name__ == "__main__":
    main()
