import pytest

from app.domain.enums import LifecycleStage
from app.verdict.severity import (
    FIELD_SEVERITY_DEFAULT,
    SEVERITY,
    UnknownRuleError,
    severity_for,
)


def test_severity_map_exhaustive_over_registry():
    import app.rules  # noqa: F401 — side-effect registration
    from app.rules.registry import all_rules

    regs = all_rules()
    missing = [rid for rid in regs if rid not in SEVERITY]
    assert missing == [], f"rules missing a severity mapping: {missing}"


def test_field_severity_default_covers_every_lifecycle_stage():
    for stage in LifecycleStage:
        assert stage in FIELD_SEVERITY_DEFAULT


def test_no_clause_found_is_always_informational():
    assert (
        severity_for(
            rule_id="R01_docs_release_30d", lifecycle_stage=None, verdict="no_clause_found"
        )
        == "informational"
    )
    assert (
        severity_for(rule_id=None, lifecycle_stage="servicing", verdict="no_clause_found")
        == "informational"
    )


def test_rule_decided_verdict_uses_severity_map():
    assert (
        severity_for(rule_id="R01_docs_release_30d", lifecycle_stage=None, verdict="violation")
        == "critical"
    )


def test_unknown_rule_id_raises():
    with pytest.raises(UnknownRuleError):
        severity_for(rule_id="R999_not_real", lifecycle_stage=None, verdict="violation")


def test_field_decided_verdict_uses_lifecycle_default():
    assert severity_for(rule_id=None, lifecycle_stage="closure", verdict="violation") == "critical"
    assert severity_for(rule_id=None, lifecycle_stage="servicing", verdict="compliant") == "minor"


def test_model_cannot_influence_severity_via_verdict_draft():
    from app.domain.verdicts import VerdictDraft

    assert "severity" not in VerdictDraft.model_fields
