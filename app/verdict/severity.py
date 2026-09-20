"""Static severity map. LLD §10.3.

Severity is a business judgement and is therefore static, never model-assigned — a
model-assigned severity would drift between model versions and make the portfolio view
incomparable across time. `VerdictDraft` (app/domain/verdicts.py) has no `severity` field,
so the model cannot influence it even by accident.

The map is exhaustive over every registered rule id (asserted by
tests/unit/verdict/test_severity.py, which iterates the live registry) — LLD §10.3's own
map is elided with `...` and stops at ten of the twenty-eight rules; the remaining eighteen
are filled in here by the same critical/major/minor judgement the LLD's own examples use:
critical for anything touching money movement, document release, disbursal, biometric/consent
or device-restriction preconditions; major for contact-conduct and disclosure rules whose
breach is a process failure rather than a financial or physical-safety one; minor for
notice-content completeness rules.
"""

from app.domain.enums import LifecycleStage

SEVERITY: dict[str, str] = {
    "R01_docs_release_30d": "critical",
    "R02_docs_release_compensation": "critical",
    "R02b_lost_documents": "critical",
    "R03_apr_consistency": "critical",
    "R04_apr_computation": "critical",
    "R05_penal_not_interest": "major",
    "R06_no_capitalisation": "major",
    "R07_cooling_off_disclosed": "major",
    "R08_disbursal_to_borrower": "critical",
    "R09_no_pool_account": "critical",
    "R10_lsp_fee_borne_by_lender": "major",
    "R11_grievance_officer_in_kfs": "minor",
    "R12_grievance_escalation_disclosed": "minor",
    "R13_offshore_deletion": "critical",
    "R14_no_biometric": "critical",
    "R15_agent_identity_notified": "minor",
    "R16_contact_window": "major",
    "R17_microfinance_contact_hours": "major",
    "R18_recording_retention": "minor",
    "R19_agent_certified": "major",
    "R20_no_third_party_contact": "critical",
    "R21_no_social_media_disclosure": "critical",
    "R22_visit_prior_intimation": "major",
    "R23_device_restriction_preconditions": "critical",
    "R24_restoration_compensation": "critical",
    "R25_grievance_officer_on_recovery_comms": "minor",
    "R26_kfs_validity": "major",
    "R27_kfs_summary_reproduced": "minor",
}

FIELD_SEVERITY_DEFAULT: dict[str, str] = {
    LifecycleStage.SANCTION: "major",
    LifecycleStage.COLLECTIONS: "major",
    LifecycleStage.CLOSURE: "critical",
    LifecycleStage.SERVICING: "minor",
    LifecycleStage.ORIGINATION: "minor",
    LifecycleStage.DISBURSEMENT: "major",
}


class UnknownRuleError(Exception):
    pass


def severity_for(*, rule_id: str | None, lifecycle_stage: str | None, verdict: str) -> str:
    if verdict == "no_clause_found":
        return "informational"
    if rule_id:
        try:
            return SEVERITY[rule_id]
        except KeyError as exc:
            raise UnknownRuleError(f"no severity mapping for rule {rule_id!r}") from exc
    if lifecycle_stage is None:
        raise ValueError("severity_for requires lifecycle_stage when rule_id is None")
    return FIELD_SEVERITY_DEFAULT[lifecycle_stage]
