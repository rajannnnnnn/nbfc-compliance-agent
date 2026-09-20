#!/usr/bin/env python3
"""Generates eval/cases/extraction_core/*.json from eval/fixtures/*/*.facts.json.

M3-T08 (extraction_core suite): the ground truth here is not invented — it is the exact
Python values scripts/gen_synthetic_docs.py used to render each fixture, recorded alongside
it as `<fixture>.facts.json` at generation time. This script only reshapes that ground truth
into the `EvalCase` (eval/loader.py) JSON shape; it introduces no new facts.

`verdict` and `check_key` are extraction-stage-irrelevant placeholders (`eval.metrics.
compute_extraction_metrics` never reads them; only `eval.loader.EvalCase`'s schema requires
the fields to be present). `mitc` fixtures are skipped — app/schema/fields.yaml registers no
fields for that doc_type (see scripts/gen_synthetic_docs.py's `_gen_mitc` docstring), so there
is nothing an extraction case could compare.
"""

import argparse
import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent / "eval" / "fixtures"
CASES_DIR = Path(__file__).parent.parent / "eval" / "cases" / "extraction_core"

_EVENT_DATE_FIELD_BY_DOC_TYPE = {
    "kfs": "kfs_issued_date",
    "closure_statement": "closure_statement_date",
}
_DEFAULT_EVENT_DATE = "2026-06-01"


def _event_date_for(doc_type: str, facts: dict[str, str]) -> str:
    key = _EVENT_DATE_FIELD_BY_DOC_TYPE.get(doc_type)
    if key and key in facts:
        return facts[key]
    if doc_type == "call_transcript" and "contact_datetime" in facts:
        return facts["contact_datetime"].split("T")[0]
    return _DEFAULT_EVENT_DATE


def generate(fixtures_dir: Path = FIXTURES_DIR, cases_dir: Path = CASES_DIR) -> list[Path]:
    cases_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for facts_path in sorted(fixtures_dir.glob("*/*.facts.json")):
        payload = json.loads(facts_path.read_text())
        doc_type = payload["doc_type"]
        if doc_type == "mitc":
            continue
        facts = payload["facts"]
        if not facts:
            continue

        fixture_path = facts_path.with_suffix("").with_suffix(".txt")
        case_ref = f"EV-EXTRACT-{doc_type.upper()}-{fixture_path.stem.rsplit('_', 1)[-1]}"
        case = {
            "case_ref": case_ref,
            "suite": "extraction_core",
            "stage": "extraction",
            "doc_type": doc_type,
            "input_ref": f"{doc_type}/{fixture_path.name}",
            "event_date": _event_date_for(doc_type, facts),
            "account_profile": {
                "product_type": facts.get("loan_type", "personal"),
                "is_microfinance": facts.get("loan_type") == "microfinance",
                "is_digital_lending": False,
                "device_financed": facts.get("device_financed_by_loan_flag", "false") == "true",
            },
            "expected": {
                "facts": facts,
                "check_key": "extraction",
                "verdict": "n/a",
                "decisive_citations": [],
                "context_citations": [],
                "forbidden_citations": [],
            },
            "tolerance": {},
            "is_adversarial": False,
            "notes": (
                f"Ground truth is the exact value scripts/gen_synthetic_docs.py used to "
                f"render {fixture_path.name}, not a separately authored expectation."
            ),
        }
        out_path = cases_dir / f"{case_ref}.json"
        out_path.write_text(json.dumps(case, indent=2) + "\n")
        written.append(out_path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", default=str(FIXTURES_DIR))
    parser.add_argument("--out", default=str(CASES_DIR))
    args = parser.parse_args()
    written = generate(Path(args.fixtures), Path(args.out))
    print(f"wrote {len(written)} extraction_core eval cases to {args.out}")


if __name__ == "__main__":
    main()
