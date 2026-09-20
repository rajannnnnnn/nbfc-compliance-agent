import app.rules  # noqa: F401 — triggers registration
from app.rules.registry import is_shadow


def test_verified_instrument_not_shadow():
    assert (
        is_shadow("R01_docs_release_30d", instrument_verification={"RBC2025": "rbi_verified"})
        is False
    )


def test_unverified_instrument_is_shadow():
    assert (
        is_shadow("R01_docs_release_30d", instrument_verification={"RBC2025": "unverified"}) is True
    )


def test_secondary_sourced_instrument_is_shadow():
    assert (
        is_shadow(
            "R16_contact_window", instrument_verification={"RBC-AMD2026": "secondary_sourced"}
        )
        is True
    )


def test_missing_instrument_defaults_to_shadow():
    assert is_shadow("R16_contact_window", instrument_verification={}) is True


def test_placeholder_corpus_puts_every_rule_in_shadow():
    """ADR-001: every instrument in the shipped placeholder corpus is verification_status
    'unverified' or 'secondary_sourced' — no rule should ever be non-shadow against it."""
    from app.rules.registry import all_rules

    placeholder_verification = {
        "DL2025": "unverified",
        "KFS2024": "unverified",
        "RBC2025": "unverified",
        "RBC-AMD2026": "secondary_sourced",
        "RBC-AMD2026-DRAFT": "unverified",
    }
    for rid in all_rules():
        assert is_shadow(rid, instrument_verification=placeholder_verification) is True, rid
