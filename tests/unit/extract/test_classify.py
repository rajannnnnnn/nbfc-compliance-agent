from unittest.mock import AsyncMock

from app.config import Settings
from app.extract.classify import ClassificationResult, classify_document
from app.llm.client import LLMClient


def _settings(**kw) -> Settings:
    defaults = dict(
        database_url="postgresql+asyncpg://u:p@localhost/db", classify_confidence_floor=0.70
    )
    defaults.update(kw)
    return Settings(_env_file=None, **defaults)  # type: ignore[call-arg]


async def test_high_confidence_returns_as_is():
    settings = _settings()
    client = LLMClient(settings)
    client.structured = AsyncMock(
        return_value=(
            ClassificationResult(doc_type="kfs", confidence=0.95, reason="looks like a KFS"),
            None,
        )
    )
    result = await classify_document("some document text", client=client, settings=settings)
    assert result.doc_type == "kfs"
    assert result.confidence == 0.95


async def test_low_confidence_downgrades_to_unknown():
    settings = _settings()
    client = LLMClient(settings)
    client.structured = AsyncMock(
        return_value=(
            ClassificationResult(doc_type="kfs", confidence=0.40, reason="uncertain"),
            None,
        )
    )
    result = await classify_document("ambiguous text", client=client, settings=settings)
    assert result.doc_type == "unknown"
    assert result.confidence == 0.40


async def test_only_first_2000_chars_sent():
    settings = _settings()
    client = LLMClient(settings)
    captured = {}

    async def fake_structured(*, model_cls, model, messages, stage):
        captured["prompt"] = messages[0]["content"]
        return ClassificationResult(doc_type="kfs", confidence=0.9, reason="x"), None

    client.structured = fake_structured
    long_text = "A" * 5000
    await classify_document(long_text, client=client, settings=settings)
    # the document text embedded in the prompt must be truncated to 2000 chars — a run of
    # 2001+ consecutive A's would only appear if the full 5000-char text leaked through
    assert "A" * 2001 not in captured["prompt"]
    assert "A" * 2000 in captured["prompt"]
