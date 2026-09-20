"""Loads eval case JSON files. LLD §17.1.

Per M9-eval ADR (see docs/DECISIONS.md): this harness ships a small, honest set of real
cases per suite — not the LLD §17.3 minimum sizes (150/60/30/40/25/30/20). Building those
minimums means synthesizing hundreds of realistic documents across six deep document types,
which is out of scope for this pass; the harness itself (loader, runner, metrics, report
writer) is complete and correct against however many cases exist in `eval/cases/<suite>/`.
"""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

CASES_DIR = Path(__file__).parent / "cases"


class AccountProfile(BaseModel):
    product_type: str
    is_microfinance: bool = False
    is_digital_lending: bool = False
    device_financed: bool = False


class ExpectedResult(BaseModel):
    facts: dict[str, str] = {}
    check_key: str
    verdict: str
    decisive_citations: list[str] = []
    context_citations: list[str] = []
    forbidden_citations: list[str] = []


class ConflictDocumentSpec(BaseModel):
    """One document's worth of facts for a `stage: "conflicts"` case. A conflict is
    cross-document by definition (LLD §12), so a single `doc_type`/`facts` pair on the case
    itself (as extraction/verdict cases use) cannot express it."""

    doc_type: str
    facts: dict[str, str] = {}


class ConflictExpected(BaseModel):
    conflict_expected: bool
    raises_check: str | None = None


class EvalCase(BaseModel):
    case_ref: str
    suite: str
    stage: str
    doc_type: str | None = None
    input_ref: str | None = None
    event_date: str
    account_profile: AccountProfile
    expected: ExpectedResult = ExpectedResult(check_key="n/a", verdict="n/a")
    documents: list[ConflictDocumentSpec] = []
    conflict_expected: ConflictExpected | None = None
    tolerance: dict[str, Any] = {}
    is_adversarial: bool = False
    notes: str | None = None


def load_suite(suite: str, *, cases_dir: Path | str = CASES_DIR) -> list[EvalCase]:
    suite_dir = Path(cases_dir) / suite
    if not suite_dir.is_dir():
        raise FileNotFoundError(f"no eval/cases directory for suite {suite!r}: {suite_dir}")
    cases = []
    for path in sorted(suite_dir.glob("*.json")):
        with open(path) as f:
            raw = json.load(f)
        case = EvalCase.model_validate(raw)
        if case.suite != suite:
            raise ValueError(f"{path}: suite field {case.suite!r} != directory {suite!r}")
        cases.append(case)
    return cases
