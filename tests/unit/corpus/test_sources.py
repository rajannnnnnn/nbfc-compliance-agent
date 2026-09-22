import pytest
from pydantic import ValidationError

from app.corpus.sources import CorpusSourcesConfig, load_corpus_sources

REAL_PATH = "app/corpus/corpus_sources.yaml"


def test_all_five_instrument_codes_present():
    cfg = load_corpus_sources(REAL_PATH)
    codes = {i.code for i in cfg.instruments}
    assert codes == {"DL2025", "KFS2024", "RBC2025", "RBC-AMD2026", "RBC-AMD2026-DRAFT"}


def test_every_instrument_declares_required_fields():
    cfg = load_corpus_sources(REAL_PATH)
    for inst in cfg.instruments:
        assert inst.source_url
        assert inst.status
        assert inst.verification_status
        assert inst.dialect in ("roman", "paren_numeral")


def test_dl2025_para_overrides_match_prd():
    cfg = load_corpus_sources(REAL_PATH)
    dl = cfg.get("DL2025")
    assert dl.para_overrides["6"].effective_from.isoformat() == "2025-11-01"
    assert dl.para_overrides["17"].effective_from.isoformat() == "2025-06-15"


def test_draft_is_not_citable_and_has_no_effective_from():
    cfg = load_corpus_sources(REAL_PATH)
    draft = cfg.get("RBC-AMD2026-DRAFT")
    assert draft.status == "draft"
    assert draft.citable is False
    assert draft.effective_from is None


def test_rbc_amd2026_is_secondary_sourced():
    cfg = load_corpus_sources(REAL_PATH)
    amd = cfg.get("RBC-AMD2026")
    assert amd.verification_status == "secondary_sourced"
    assert amd.status == "notified_not_yet_effective"


def test_rejects_unknown_status():
    raw = {
        "version": 1,
        "instruments": [
            {
                "code": "X",
                "official_title": "t",
                "source_url": "x.txt",
                "status": "bogus",
                "effective_from": None,
                "citable": True,
                "verification_status": "unverified",
                "dialect": "roman",
            }
        ],
    }
    with pytest.raises(ValidationError):
        CorpusSourcesConfig.model_validate(raw)


def test_draft_status_with_citable_true_rejected():
    raw = {
        "version": 1,
        "instruments": [
            {
                "code": "X",
                "official_title": "t",
                "source_url": "x.txt",
                "status": "draft",
                "effective_from": None,
                "citable": True,
                "verification_status": "unverified",
                "dialect": "roman",
            }
        ],
    }
    with pytest.raises(ValidationError):
        CorpusSourcesConfig.model_validate(raw)


def test_duplicate_codes_rejected():
    entry = {
        "code": "X",
        "official_title": "t",
        "source_url": "x.txt",
        "status": "in_force",
        "effective_from": "2025-01-01",
        "citable": True,
        "verification_status": "unverified",
        "dialect": "roman",
    }
    raw = {"version": 1, "instruments": [entry, dict(entry)]}
    with pytest.raises(ValidationError):
        CorpusSourcesConfig.model_validate(raw)
