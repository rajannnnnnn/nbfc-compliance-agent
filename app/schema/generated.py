"""Builds, per document type, a Pydantic model whose fields are the registry entries for that
type, all optional, each annotated with its description. That model is passed to the
structured-output enforcement layer as the JSON schema. LLD §5.2.

Each field is a `FieldExtraction` object, not a bare value — the extraction prompt (LLD §9.1)
requires `quoted_span` and `is_absent` per field, not just a value, so the model the LLM fills
in has to carry that shape.
"""

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, create_model

from app.schema.registry import FieldRegistry

if TYPE_CHECKING:
    from app.schema.registry import FieldSpec


class FieldExtraction(BaseModel):
    value_raw: str | None = None
    is_absent: bool = False
    quoted_span: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


def _build_model(model_name: str, specs: list["FieldSpec"]) -> type[BaseModel]:
    field_defs: dict[str, Any] = {}
    for spec in specs:
        field_defs[spec.key] = (
            FieldExtraction,
            Field(
                default_factory=lambda: FieldExtraction(is_absent=True),
                description=spec.description,
            ),
        )
    model: type[BaseModel] = create_model(model_name, **field_defs)
    return model


def build_model_for_doc_type(registry: FieldRegistry, doc_type: str) -> type[BaseModel]:
    fields = registry.for_doc_type(doc_type)
    model_name = f"{doc_type.title().replace('_', '')}Fields"
    return _build_model(model_name, fields)


def build_model_for_field_group(
    doc_type: str, group_index: int, specs: list["FieldSpec"]
) -> type[BaseModel]:
    """A model over one slice of a doc_type's fields — ADR-041: some providers' structured-
    output mode rejects a schema with too many fields in one call, so a large doc_type is
    split into several of these rather than one `build_model_for_doc_type` call."""
    model_name = f"{doc_type.title().replace('_', '')}FieldsGroup{group_index}"
    return _build_model(model_name, specs)


def build_all_models(registry: FieldRegistry, doc_types: list[str]) -> dict[str, type[BaseModel]]:
    return {dt: build_model_for_doc_type(registry, dt) for dt in doc_types}
