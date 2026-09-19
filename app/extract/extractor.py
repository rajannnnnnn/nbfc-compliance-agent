"""Schema-constrained extraction call + JSON repair. LLD §9.1.

The only public entry point for the raw model call — normalisation, redaction, span
verification and persistence happen in app/extract/service.py, which calls this.
"""

from pathlib import Path

from pydantic import BaseModel

from app.config import Settings
from app.llm.client import LLMClient
from app.schema.generated import build_model_for_doc_type
from app.schema.registry import FieldRegistry

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "extract" / "document_facts.v1.md"
PROMPT_VERSION = "document_facts.v1"


def _field_table(registry: FieldRegistry, doc_type: str) -> str:
    lines = []
    for spec in registry.for_doc_type(doc_type):
        enum_note = f" (one of: {', '.join(spec.enum_values)})" if spec.enum_values else ""
        lines.append(f"- {spec.key} [{spec.type}]{enum_note}: {spec.description.strip()}")
    return "\n".join(lines)


async def extract_raw_fields(
    *,
    document_text: str,
    doc_type: str,
    client: LLMClient,
    registry: FieldRegistry,
    settings: Settings,
) -> BaseModel:
    """Returns an instance of the doc-type-specific model built by app/schema/generated.py,
    one FieldExtraction per registered field for that doc_type."""
    model_cls = build_model_for_doc_type(registry, doc_type)
    prompt_template = PROMPT_PATH.read_text()
    prompt = prompt_template.format(
        doc_type=doc_type,
        document_text=document_text,
        field_table=_field_table(registry, doc_type),
    )
    parsed, _record = await client.structured(
        model_cls=model_cls,
        model=settings.extract_model,
        messages=[{"role": "user", "content": prompt}],
        stage="extract",
        adapter_id=settings.extract_adapter_id,
    )
    return parsed
