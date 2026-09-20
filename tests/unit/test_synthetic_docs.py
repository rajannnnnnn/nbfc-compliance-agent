"""M3-T07: synthetic document generator. Every generated fixture must carry a visible
synthetic banner (CLAUDE.md §2.4) and must never contain a value shaped like a real
AADHAAR/PAN/ACCOUNT pattern (app/extract/redact.py's own patterns, reused here directly
so this test can never silently drift from what the redactor actually looks for)."""

import random

from app.extract.redact import PATTERNS
from scripts.gen_synthetic_docs import (
    _GENERATORS,
    SYNTHETIC_BANNER,
    generate_all,
    generate_document,
)

_SENSITIVE_TAGS = {"AADHAAR", "PAN", "ACCOUNT"}


def test_generates_at_least_150_documents_across_six_types(tmp_path):
    written = generate_all(tmp_path, count=150)
    assert len(written) >= 150
    doc_types = {p.parent.name for p in written}
    assert doc_types == set(_GENERATORS)
    for doc_type in _GENERATORS:
        assert len(list((tmp_path / doc_type).glob("*.txt"))) >= 25


def test_every_document_carries_the_synthetic_banner(tmp_path):
    written = generate_all(tmp_path, count=150)
    for path in written:
        assert SYNTHETIC_BANNER in path.read_text()


def test_no_document_contains_a_real_looking_pan_aadhaar_or_account_pattern(tmp_path):
    written = generate_all(tmp_path, count=150)
    for path in written:
        text = path.read_text()
        for tag, pattern in PATTERNS:
            if tag in _SENSITIVE_TAGS:
                assert not pattern.search(text), f"{path}: matched {tag} pattern"


def test_layout_and_date_format_vary_across_the_same_doc_type():
    rng = random.Random(7)
    samples = {generate_document("kfs", rng) for _ in range(20)}
    assert len(samples) > 1


def test_deterministic_given_the_same_seed(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    written_a = generate_all(a, count=30, seed=99)
    written_b = generate_all(b, count=30, seed=99)
    texts_a = [p.read_text() for p in sorted(written_a)]
    texts_b = [p.read_text() for p in sorted(written_b)]
    assert texts_a == texts_b
