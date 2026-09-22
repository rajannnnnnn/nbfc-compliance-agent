"""LLD §19: an AST test walks app/rules/ and fails on any call to date.today(),
datetime.now(), or a session import — a rule that reads the clock or touches I/O is not
reproducible and cannot be historically re-assessed."""

import ast
from pathlib import Path

FORBIDDEN_CALLS = {"today", "now"}
FORBIDDEN_IMPORTS = {"sqlalchemy", "httpx", "asyncpg", "requests"}


def _rule_files():
    return [
        p
        for p in Path("app/rules").glob("*.py")
        if p.name not in ("__init__.py", "base.py", "registry.py")
    ]


def test_no_rule_reads_the_clock():
    violations = []
    for path in _rule_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                attr = getattr(node.func, "attr", None)
                if attr in FORBIDDEN_CALLS:
                    violations.append((str(path), attr))
    assert violations == [], f"rules reading the clock: {violations}"


def test_no_rule_imports_session_or_network():
    violations = []
    for path in _rule_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module.split(".")[0]]
            for m in modules:
                if m in FORBIDDEN_IMPORTS:
                    violations.append((str(path), m))
    assert violations == [], f"rules importing session/network modules: {violations}"


def test_no_rule_evaluate_is_async():
    violations = []
    for path in _rule_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "evaluate":
                violations.append(str(path))
    assert violations == [], f"async evaluate() found in: {violations}"


def test_all_rules_registered_and_paths_canonical():
    import app.rules  # noqa: F401
    from app.rules.registry import CANONICAL_PATH_RE, all_rules

    regs = all_rules()
    assert len(regs) == 28  # 27 numbered + R02b
    for rid, reg in regs.items():
        inst = reg.rule_cls()
        for p in inst.clause_paths:
            assert CANONICAL_PATH_RE.match(p), f"{rid}: non-canonical path {p}"
