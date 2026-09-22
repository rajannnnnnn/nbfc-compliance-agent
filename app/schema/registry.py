"""Loads, validates and indexes fields.yaml. LLD §5.2."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from app.domain.enums import DocType, ValueType

_KNOWN_NORMALISATION_DIRECTIVES = {"unit", "max", "formats", "prefer", "timezone", "assume_local"}


class FieldSpec(BaseModel):
    key: str
    label: str
    type: str
    doc_types: list[str]
    lifecycle_stage: str
    required_for: list[str] = []
    enum_values: list[str] | None = None
    redaction_exempt: bool = False
    normalisation: dict[str, Any] = {}
    description: str


class RegistryValidationError(Exception):
    pass


class FieldRegistry:
    def __init__(self, path: str | Path):
        with open(path) as f:
            raw = yaml.safe_load(f)
        self._fields: dict[str, FieldSpec] = {}
        self._duplicate_keys: list[str] = []
        for entry in raw["fields"]:
            spec = FieldSpec.model_validate(entry)
            if spec.key in self._fields:
                self._duplicate_keys.append(spec.key)
            self._fields[spec.key] = spec

    def get(self, key: str) -> FieldSpec:
        return self._fields[key]

    def for_doc_type(self, doc_type: str) -> list[FieldSpec]:
        return [f for f in self._fields.values() if doc_type in f.doc_types]

    def required_for(self, doc_type: str) -> list[str]:
        return [f.key for f in self._fields.values() if doc_type in f.required_for]

    def all_keys(self) -> set[str]:
        return set(self._fields.keys())

    def validate(self) -> None:
        """Fatal on: duplicate keys; enum type without enum_values; doc_type not in the
        doc_type enum; required_for entry absent from doc_types; unknown normalisation
        directive; field referenced by a rule or by pinning.yaml but not declared."""
        errors: list[str] = [f"duplicate field key: {key}" for key in self._duplicate_keys]

        for key, spec in self._fields.items():
            if spec.type == "enum" and not spec.enum_values:
                errors.append(f"{key}: type=enum requires enum_values")

            try:
                ValueType(spec.type)
            except ValueError:
                errors.append(f"{key}: unknown value type {spec.type!r}")

            for dt in spec.doc_types:
                try:
                    DocType(dt)
                except ValueError:
                    errors.append(f"{key}: doc_type {dt!r} is not in the doc_type enum")

            for dt in spec.required_for:
                if dt not in spec.doc_types:
                    errors.append(f"{key}: required_for entry {dt!r} is absent from doc_types")

            unknown_directives = set(spec.normalisation) - _KNOWN_NORMALISATION_DIRECTIVES
            if unknown_directives:
                errors.append(f"{key}: unknown normalisation directive(s) {unknown_directives}")

        if errors:
            raise RegistryValidationError("; ".join(errors))

    def validate_external_references(self, referenced_keys: set[str]) -> None:
        """Fatal if a rule or pinning.yaml references a field key not declared here."""
        unknown = referenced_keys - self.all_keys()
        if unknown:
            raise RegistryValidationError(
                f"field key(s) referenced but not declared in fields.yaml: {sorted(unknown)}"
            )
