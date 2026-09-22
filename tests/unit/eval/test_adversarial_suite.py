"""No live LLM call here -- these check the adversarial suite's own construction, not model
behavior. See docs/DECISIONS.md ADR-049."""

from pathlib import Path

from eval.loader import load_suite

FIXTURES_DIR = Path(__file__).parent.parent.parent.parent / "eval" / "fixtures"

CASES = load_suite("adversarial")

# The clean, non-adversarial fixture each adversarial variant was derived from -- ground
# truth must match it exactly, proving the adversarial content didn't leak into the expected
# facts.
_BASE_FIXTURE = {
    "kfs_inject_0000": "kfs/kfs_0000",
    "kfs_fakeclause_0000": "kfs/kfs_0000",
    "kfs_ocrnoise_0000": "kfs/kfs_0000",
    "loan_agreement_inject_0000": "loan_agreement/loan_agreement_0000",
    "loan_agreement_fakeclause_0000": "loan_agreement/loan_agreement_0000",
    "call_transcript_inject_0000": "call_transcript/call_transcript_0000",
    "call_transcript_ocrnoise_0000": "call_transcript/call_transcript_0000",
    "call_transcript_fakeclause_0000": "call_transcript/call_transcript_0000",
}

# RBI instruments in this corpus family never use decimal clause numbering (CLAUDE.md SS2.6);
# every planted "fake clause reference" fixture must use exactly that forbidden shape, so a
# citation to it is unambiguously fabricated, not a real path this corpus could ever contain.
_DECIMAL_PATH_RE = __import__("re").compile(r"[A-Za-z0-9-]+/Ch\.[IVXLC]+/\d+\.\d+\([a-z]\)")


def test_every_case_is_flagged_adversarial():
    assert CASES, "adversarial suite has no cases"
    for case in CASES:
        assert case.is_adversarial is True, case.case_ref


def test_ground_truth_matches_the_clean_base_fixture():
    import json

    for case in CASES:
        stem = Path(case.input_ref).stem
        base = _BASE_FIXTURE[stem]
        base_facts = json.loads((FIXTURES_DIR / f"{base}.facts.json").read_text())["facts"]
        assert case.expected.facts == base_facts, (
            f"{case.case_ref}: adversarial content changed expected ground truth relative "
            f"to the clean {base} fixture it was derived from"
        )


def test_fakeclause_fixtures_cite_a_decimal_path_forbidden_by_claude_md():
    fakeclause_cases = [c for c in CASES if "fakeclause" in c.input_ref]
    assert fakeclause_cases, "no fakeclause-technique cases found"
    for case in fakeclause_cases:
        text = (FIXTURES_DIR / case.input_ref).read_text()
        assert _DECIMAL_PATH_RE.search(text), (
            f"{case.case_ref}: expected a planted decimal-numbered clause path "
            "(the shape CLAUDE.md SS2.6 says this corpus family never uses)"
        )


def test_inject_fixtures_contain_an_instruction_style_sentence():
    inject_cases = [c for c in CASES if "inject" in c.input_ref]
    assert inject_cases, "no injection-technique cases found"
    markers = ("ignore", "disregard", "mark", "compliant", "skip")
    for case in inject_cases:
        text = (FIXTURES_DIR / case.input_ref).read_text().lower()
        assert any(m in text for m in markers), case.case_ref


def test_ocrnoise_fixtures_keep_every_base_field_line_verbatim():
    """The noise must sit around, not inside, the field-bearing sentences: every content
    line from the clean base fixture must survive character-for-character in the noised
    variant. Otherwise a failure to extract would be indistinguishable from a genuine
    OCR-robustness gap versus ground truth that was never recoverable in the first place."""
    ocr_cases = [c for c in CASES if "ocrnoise" in c.input_ref]
    assert ocr_cases, "no ocrnoise-technique cases found"
    for case in ocr_cases:
        stem = Path(case.input_ref).stem
        base = _BASE_FIXTURE[stem]
        base_lines = [
            ln
            for ln in (FIXTURES_DIR / f"{base}.txt").read_text().splitlines()
            # Only field-bearing lines matter here (a "Label: value" shape); the bare
            # document-title header line (e.g. "KEY FACTS STATEMENT") carries no field and
            # is a legitimate noise target, same as any other cosmetic OCR artifact.
            if ln.strip() and not ln.startswith("***") and ":" in ln
        ]
        noised_text = (FIXTURES_DIR / case.input_ref).read_text()
        for line in base_lines:
            assert line in noised_text, (
                f"{case.case_ref}: base field line {line!r} was altered or removed, not "
                "just surrounded, by the OCR/unicode noise"
            )
