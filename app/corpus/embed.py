"""Batched embedding with retry. LLD §6.1 / M1-T06.

Routes through LiteLLM so no provider SDK is imported outside app/llm/ — but this module is
corpus-side, not stage-side, so it goes through the shared client rather than importing a
provider SDK directly (CLAUDE.md §3 "No provider SDK imported outside app/llm/").
"""

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import Settings
from app.llm.client import LLMClient, TransientLLMError


class EmbeddingError(Exception):
    pass


@retry(
    retry=retry_if_exception_type(TransientLLMError),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
async def _embed_batch(
    client: LLMClient, texts: list[str], settings: Settings
) -> list[list[float]]:
    return await client.embed(
        texts, model=settings.embedding_model, dimensions=settings.embedding_dimension
    )


async def embed_texts(
    texts: list[str], *, client: LLMClient, settings: Settings
) -> list[list[float]]:
    """Batches at settings.embedding_batch_size; a permanent failure on any batch fails the
    whole ingest rather than writing partial vectors — a corpus snapshot with some clauses
    embedded and others not is worse than no snapshot at all."""
    vectors: list[list[float]] = []
    batch_size = settings.embedding_batch_size
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        try:
            batch_vectors = await _embed_batch(client, batch, settings)
        except TransientLLMError as exc:
            raise EmbeddingError(f"embedding failed permanently after retries: {exc}") from exc
        for v in batch_vectors:
            if len(v) != settings.embedding_dimension:
                raise EmbeddingError(
                    f"embedding dimension mismatch: got {len(v)}, expected {settings.embedding_dimension}"
                )
        vectors.extend(batch_vectors)
    if len(vectors) != len(texts):
        raise EmbeddingError(f"embedded {len(vectors)} of {len(texts)} chunks")
    return vectors
