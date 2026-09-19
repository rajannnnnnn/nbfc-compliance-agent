from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.corpus.embed import EmbeddingError, embed_texts
from app.llm.client import LLMClient, TransientLLMError


def _settings(**kw) -> Settings:
    defaults = dict(
        database_url="postgresql+asyncpg://u:p@localhost/db",
        embedding_dimension=4,
        embedding_batch_size=2,
    )
    defaults.update(kw)
    return Settings(_env_file=None, **defaults)  # type: ignore[call-arg]


async def test_batches_at_configured_size():
    settings = _settings()
    client = LLMClient(settings)
    calls = []

    async def fake_embed(texts, **kw):
        calls.append(list(texts))
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    client.embed = fake_embed  # type: ignore[method-assign]
    result = await embed_texts(["a", "b", "c", "d", "e"], client=client, settings=settings)
    assert len(result) == 5
    assert [len(c) for c in calls] == [2, 2, 1]


async def test_dimension_mismatch_raises():
    settings = _settings()
    client = LLMClient(settings)
    client.embed = AsyncMock(return_value=[[0.1, 0.2]])  # wrong dimension
    with pytest.raises(EmbeddingError, match="dimension mismatch"):
        await embed_texts(["a"], client=client, settings=settings)


async def test_permanent_failure_after_retries_raises_embedding_error():
    settings = _settings()
    client = LLMClient(settings)
    client.embed = AsyncMock(side_effect=TransientLLMError("boom"))
    with pytest.raises(EmbeddingError, match="permanently"):
        await embed_texts(["a", "b"], client=client, settings=settings)


async def test_chunk_count_matches_node_count():
    settings = _settings(embedding_batch_size=64)
    client = LLMClient(settings)
    texts = [f"clause {i}" for i in range(37)]

    async def fake_embed(t, **kw):
        return [[0.0, 0.0, 0.0, 0.0] for _ in t]

    client.embed = fake_embed  # type: ignore[method-assign]
    result = await embed_texts(texts, client=client, settings=settings)
    assert len(result) == len(texts)
