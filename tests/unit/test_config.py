import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings


def _base(**overrides):
    kwargs = {"database_url": "postgresql+asyncpg://u:p@localhost/db", **overrides}
    return Settings(_env_file=None, **kwargs)  # type: ignore[call-arg]


def test_rejects_unknown_env_var(monkeypatch):
    monkeypatch.setenv("CC_NOT_A_REAL_KEY", "x")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_env_must_be_one_of_three():
    with pytest.raises(ValidationError):
        _base(env="staging")
    assert _base(env="ci").env == "ci"


def test_serving_mode_restricted():
    with pytest.raises(ValidationError):
        _base(serving_mode="bespoke")
    assert _base(serving_mode="tuned_gpu").serving_mode == "tuned_gpu"


def test_missing_database_url_raises():
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_get_settings_is_cached(monkeypatch):
    monkeypatch.setenv("CC_DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    get_settings.cache_clear()
    a = get_settings()
    b = get_settings()
    assert a is b
    get_settings.cache_clear()


def test_defaults_match_lld_section_2():
    s = _base()
    assert s.embedding_dimension == 1536  # ADR-004, not the LLD's literal 3072
    assert s.rrf_weight_pinned == 2.5  # ADR-020, not the LLD's literal 2.0
    assert s.retrieve_vector_k == 12
    assert s.retrieve_lexical_k == 12
    assert s.retrieve_final_k == 8
    assert s.span_budget_ratio == 0.15
    assert s.fail_boot_on_pinning_mismatch is True
