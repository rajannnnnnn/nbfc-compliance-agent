"""Loads and validates app/corpus/corpus_sources.yaml. M1-T01."""

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, field_validator, model_validator

VALID_STATUSES = {"in_force", "notified_not_yet_effective", "draft", "superseded"}
VALID_VERIFICATION = {"rbi_verified", "secondary_sourced", "unverified"}


class ParaOverride(BaseModel):
    effective_from: date | None = None
    effective_to: date | None = None


class InstrumentSource(BaseModel):
    code: str
    official_title: str
    circular_number: str | None = None
    issued_on: date | None = None
    source_url: str
    status: str
    effective_from: date | None
    effective_to: date | None = None
    citable: bool
    verification_status: str
    verification_note: str | None = None
    applies_to_entity_types: list[str] = ["nbfc"]
    dialect: Literal["roman", "paren_numeral"]
    has_annex: bool = False
    para_overrides: dict[str, ParaOverride] = {}

    @field_validator("status")
    @classmethod
    def _status_valid(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"unknown status {v!r}, must be one of {VALID_STATUSES}")
        return v

    @field_validator("verification_status")
    @classmethod
    def _verification_valid(cls, v: str) -> str:
        if v not in VALID_VERIFICATION:
            raise ValueError(
                f"unknown verification_status {v!r}, must be one of {VALID_VERIFICATION}"
            )
        return v

    @model_validator(mode="after")
    def _status_and_effective_from_agree(self) -> "InstrumentSource":
        if self.status == "draft" and self.effective_from is not None:
            raise ValueError(f"{self.code}: status=draft must have effective_from=null")
        if self.status == "notified_not_yet_effective" and self.effective_from is None:
            raise ValueError(
                f"{self.code}: status=notified_not_yet_effective requires effective_from"
            )
        if self.status == "draft" and self.citable:
            raise ValueError(f"{self.code}: a draft instrument must be citable=false")
        return self


class Supersession(BaseModel):
    superseding_code: str
    superseded_circular_number: str
    superseded_title: str
    superseded_on: date


class CorpusSourcesConfig(BaseModel):
    version: int
    instruments: list[InstrumentSource]
    supersessions: list[Supersession] = []
    reference_title_patterns: dict[str, list[str]] = {}

    @model_validator(mode="after")
    def _no_duplicate_codes(self) -> "CorpusSourcesConfig":
        codes = [i.code for i in self.instruments]
        dupes = {c for c in codes if codes.count(c) > 1}
        if dupes:
            raise ValueError(f"duplicate instrument codes: {dupes}")
        return self

    def get(self, code: str) -> InstrumentSource:
        for inst in self.instruments:
            if inst.code == code:
                return inst
        raise KeyError(f"no such instrument code: {code}")


def load_corpus_sources(path: str | Path) -> CorpusSourcesConfig:
    with open(path) as f:
        raw = yaml.safe_load(f)
    return CorpusSourcesConfig.model_validate(raw)
