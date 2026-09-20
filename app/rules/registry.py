"""Decorator-based registration, shadow-mode resolution. LLD §11.2.

`shadow_if_unverified=True` makes the rule non-citable whenever any instrument behind its
`clause_paths` has `verification_status='secondary_sourced'` or `'unverified'`. A shadow rule
still evaluates and persists, with `is_shadow=true` — its behaviour is measured even though it
does not count as a finding. Every rule whose basis is the recovery amendment starts in
shadow, per ADR-001, until the user replaces the placeholder corpus with real text.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from app.rules.base import Rule

CANONICAL_PATH_RE = re.compile(r"^[A-Za-z0-9-]+/(p[0-9]+[A-Za-z]?|annex[A-Za-z])(/[^/]+){0,2}$")


@dataclass
class RuleRegistration:
    rule_cls: type
    shadow_if_unverified: bool
    severity: str


_REGISTRY: dict[str, RuleRegistration] = {}


def register(*, shadow_if_unverified: bool = True, severity: str) -> "Callable[[type], type]":
    def decorator(rule_cls: type) -> type:
        instance = rule_cls()
        for path in instance.clause_paths:
            if not CANONICAL_PATH_RE.match(path):
                raise ValueError(
                    f"{instance.id}: clause path {path!r} is not in canonical form "
                    f"'{{instrument}}/p{{para}}[/{{level2}}][/{{level3}}]' or "
                    f"'{{instrument}}/annex{{letter}}[...]' — a decimal or section-letter "
                    f"basis will never resolve at boot (CLAUDE.md §2.6)"
                )
        _REGISTRY[instance.id] = RuleRegistration(
            rule_cls=rule_cls, shadow_if_unverified=shadow_if_unverified, severity=severity
        )
        return rule_cls

    return decorator


def all_rules() -> dict[str, RuleRegistration]:
    return dict(_REGISTRY)


def rules_for_field(field_key: str) -> list[Rule]:
    return [reg.rule_cls() for reg in _REGISTRY.values() if field_key in reg.rule_cls().consumes]


def get_rule(rule_id: str) -> Rule:
    return cast(Rule, _REGISTRY[rule_id].rule_cls())


def is_shadow(rule_id: str, *, instrument_verification: dict[str, str]) -> bool:
    """`instrument_verification` maps instrument_code -> verification_status, resolved from
    the active snapshot. A rule is shadow if it opts in AND any instrument behind its
    clause_paths is not rbi_verified."""
    reg = _REGISTRY[rule_id]
    if not reg.shadow_if_unverified:
        return False
    instance = reg.rule_cls()
    for path in instance.clause_paths:
        instrument_code = path.split("/", 1)[0]
        status = instrument_verification.get(instrument_code, "unverified")
        if status != "rbi_verified":
            return True
    return False


def clear_registry_for_testing() -> None:
    _REGISTRY.clear()
