import ast
from pathlib import Path

import pytest

from app.retrieve.applicability import ApplicabilityError, require_as_of


def test_missing_as_of_raises():
    with pytest.raises(ApplicabilityError):
        require_as_of(None)


def test_as_of_passthrough():
    from datetime import date

    d = date(2026, 9, 3)
    assert require_as_of(d) == d


def test_no_call_site_passes_default_as_of():
    """AST check: no call to require_as_of or retrieve_candidates anywhere in app/ passes
    date.today() as as_of — there is no default, anywhere."""
    violations = []
    for path in Path("app").rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if func_name in ("require_as_of", "retrieve_candidates"):
                    source = ast.dump(node)
                    if "today" in source:
                        violations.append((str(path), func_name))
    assert violations == []
