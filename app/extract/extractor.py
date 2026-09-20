"""Schema-constrained extraction call + JSON repair. LLD §9.1.

The only public entry point for the raw model call — normalisation, redaction, span
verification and persistence happen in app/extract/service.py, which calls this.
"""

from pathlib import Path

from pydantic import BaseModel

from app.config import Settings
from app.llm.client import LLMClient
from app.schema.generated import build_model_for_doc_type, build_model_for_field_group
from app.schema.registry import FieldRegistry, FieldSpec

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "extract" / "document_facts.v2.md"
PROMPT_VERSION = "document_facts.v2"

# ADR-041: Gemini's structured-output mode rejected loan_agreement's 34-field schema outright
# ("too many states for serving") while kfs's 25-field schema, same nested shape, works fine
# (live-proven against the real API). Set at exactly kfs's known-good count so no currently
# working doc_type pays the extra-calls cost of splitting — only loan_agreement (34 fields,
# the sole doc_type above this threshold) does.
_MAX_FIELDS_PER_CALL = 25


def _field_table_lines(specs: list[FieldSpec]) -> str:
    lines = []
    for spec in specs:
        enum_note = f" (one of: {', '.join(spec.enum_values)})" if spec.enum_values else ""
        lines.append(f"- {spec.key} [{spec.type}]{enum_note}: {spec.description.strip()}")
    return "\n".join(lines)


def _chunk(specs: list[FieldSpec], size: int) -> list[list[FieldSpec]]:
    return [specs[i : i + size] for i in range(0, len(specs), size)]


async def _call_structured(
    *,
    model_cls: type[BaseModel],
    document_text: str,
    doc_type: str,
    field_table: str,
    prompt_template: str,
    client: LLMClient,
    settings: Settings,
) -> BaseModel:
    prompt = prompt_template.format(
        doc_type=doc_type, document_text=document_text, field_table=field_table
    )
    parsed, _record = await client.structured(
        model_cls=model_cls,
        model=settings.extract_model,
        messages=[{"role": "user", "content": prompt}],
        stage="extract",
        adapter_id=settings.extract_adapter_id,
    )
    return parsed


async def extract_raw_fields(
    *,
    document_text: str,
    doc_type: str,
    client: LLMClient,
    registry: FieldRegistry,
    settings: Settings,
) -> BaseModel:
    """Returns an instance of the doc-type-specific model built by app/schema/generated.py,
    one FieldExtraction per registered field for that doc_type.

    A doc_type with more than `_MAX_FIELDS_PER_CALL` registered fields (ADR-041) is split
    into several smaller schema-constrained calls, each sent the full document text — a
    deliberate cost/accuracy tradeoff (more input tokens billed per document) scoped to only
    the doc_types large enough to need it, in exchange for real field-level output instead of
    the provider rejecting the call outright.
    """
    fields = registry.for_doc_type(doc_type)
    prompt_template = PROMPT_PATH.read_text()

    if len(fields) <= _MAX_FIELDS_PER_CALL:
        model_cls = build_model_for_doc_type(registry, doc_type)
        return await _call_structured(
            model_cls=model_cls,
            document_text=document_text,
            doc_type=doc_type,
            field_table=_field_table_lines(fields),
            prompt_template=prompt_template,
            client=client,
            settings=settings,
        )

    merged: dict[str, object] = {}
    for group_index, group in enumerate(_chunk(fields, _MAX_FIELDS_PER_CALL)):
        group_model_cls = build_model_for_field_group(doc_type, group_index, group)
        parsed_group = await _call_structured(
            model_cls=group_model_cls,
            document_text=document_text,
            doc_type=doc_type,
            field_table=_field_table_lines(group),
            prompt_template=prompt_template,
            client=client,
            settings=settings,
        )
        merged.update(parsed_group.model_dump())

    full_model_cls = build_model_for_doc_type(registry, doc_type)
    return full_model_cls.model_validate(merged)
