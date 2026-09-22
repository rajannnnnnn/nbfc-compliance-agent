"""LLD §19: 'a second test walks app/ and fails on any import of a provider SDK outside
app/llm/.' litellm itself is exempt (it IS the routing layer); openai/anthropic/google SDKs
imported directly anywhere else are not."""

import ast
from pathlib import Path

PROVIDER_SDK_MODULES = {"openai", "anthropic", "google.generativeai", "cohere", "mistralai"}
ALLOWED_DIR = Path("app/llm")


def _imported_modules(tree: ast.AST) -> set[str]:
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def test_no_provider_sdk_outside_llm_directory():
    violations = []
    for path in Path("app").rglob("*.py"):
        if ALLOWED_DIR in path.parents:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        found = _imported_modules(tree) & PROVIDER_SDK_MODULES
        if found:
            violations.append((str(path), found))
    assert violations == [], f"provider SDK imported outside app/llm/: {violations}"
