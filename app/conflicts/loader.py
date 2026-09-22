"""Loads, validates and indexes `conflicts.yaml`. LLD §12 / M7-T01."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, model_validator

import app.rules  # noqa: F401 — side-effect registration; all_rules() is empty without it
from app.domain.enums import DocType
from app.rules.registry import all_rules
from app.schema.registry import FieldRegistry

_VALID_OPERATORS = {"equal", "equal_within", "date_order"}
_VALID_DIRECTIONS = {"after", "before", "strictly_increasing"}


class ConflictMember(BaseModel):
    doc_type: str
    field: str


class ConflictGroup(BaseModel):
    key: str
    members: list[ConflictMember]
    operator: Literal["equal", "equal_within", "date_order"]
    tolerance: int | None = None
    params: dict[str, object] = {}
    raises_check: str

    @model_validator(mode="after")
    def _shape(self) -> "ConflictGroup":
        if len(self.members) < 2:
            raise ValueError(f"group {self.key!r}: needs at least two members")
        if self.operator == "equal_within" and self.tolerance is None:
            raise ValueError(f"group {self.key!r}: equal_within requires tolerance")
        if self.operator == "date_order":
            direction = self.params.get("direction")
            if direction not in _VALID_DIRECTIONS:
                raise ValueError(
                    f"group {self.key!r}: date_order requires params.direction in "
                    f"{_VALID_DIRECTIONS}"
                )
        return self


class ConflictConfig(BaseModel):
    version: int
    groups: list[ConflictGroup]


class ConflictValidationError(Exception):
    pass


class ConflictRegistry:
    def __init__(self, groups: list[ConflictGroup]):
        self.groups = groups

    def groups_containing(self, *, doc_type: str, field_key: str) -> list[ConflictGroup]:
        return [
            g
            for g in self.groups
            if any(m.doc_type == doc_type and m.field == field_key for m in g.members)
        ]


def load(
    path: str | Path = "app/rules/conflicts.yaml",
    *,
    field_registry_path: str | Path = "app/schema/fields.yaml",
) -> ConflictRegistry:
    with open(path) as f:
        raw = yaml.safe_load(f)
    cfg = ConflictConfig.model_validate(raw)

    field_registry = FieldRegistry(field_registry_path)
    known_doc_types = {d.value for d in DocType}
    registered_rule_ids = set(all_rules().keys())

    errors: list[str] = []
    for group in cfg.groups:
        for member in group.members:
            if member.doc_type not in known_doc_types:
                errors.append(
                    f"group {group.key!r}: doc_type {member.doc_type!r} is not in the "
                    "doc_type enum"
                )
            try:
                spec = field_registry.get(member.field)
            except KeyError:
                errors.append(
                    f"group {group.key!r}: field {member.field!r} is not declared in " "fields.yaml"
                )
                continue
            if member.doc_type not in spec.doc_types:
                errors.append(
                    f"group {group.key!r}: field {member.field!r} does not list doc_type "
                    f"{member.doc_type!r} in fields.yaml"
                )
        if group.raises_check not in registered_rule_ids:
            errors.append(
                f"group {group.key!r}: raises_check {group.raises_check!r} is not a "
                "registered rule id"
            )

    if errors:
        raise ConflictValidationError("; ".join(errors))

    return ConflictRegistry(cfg.groups)
