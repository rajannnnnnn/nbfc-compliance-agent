"""Document-type classification with abstention. LLD §3.1 / HLD §3.1.

Below `classify_confidence_floor` the service returns doc_type='unknown' and the document is
held for manual typing rather than extracted against a guessed field set — a
misclassification costs more than a manual step.
"""

from pathlib import Path

from pydantic import BaseModel

from app.config import Settings
from app.domain.enums import DocType
from app.llm.client import LLMClient

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "extract" / "classify_doctype.v1.md"
PROMPT_VERSION = "classify_doctype.v1"


class ClassificationResult(BaseModel):
    doc_type: str
    confidence: float
    reason: str


async def classify_document(
    text: str, *, client: LLMClient, settings: Settings
) -> ClassificationResult:
    prompt_template = PROMPT_PATH.read_text()
    prompt = prompt_template.format(document_text=text[:2000])

    parsed, _record = await client.structured(
        model_cls=ClassificationResult,
        model=settings.classify_model,
        messages=[{"role": "user", "content": prompt}],
        stage="classify",
    )
    result = ClassificationResult.model_validate(parsed.model_dump())

    if result.confidence < settings.classify_confidence_floor:
        return ClassificationResult(
            doc_type=DocType.UNKNOWN.value,
            confidence=result.confidence,
            reason=f"below confidence floor ({settings.classify_confidence_floor}): {result.reason}",
        )
    return result
