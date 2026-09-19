"""The sole reader of the environment. Everything else takes settings by injection."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CC_", extra="forbid")

    # --- runtime -------------------------------------------------------------
    env: str = Field("local", pattern="^(local|ci|prod)$")
    log_level: str = "INFO"
    request_timeout_s: int = 30

    # --- datastores ----------------------------------------------------------
    database_url: str
    database_pool_size: int = 5
    database_max_overflow: int = 5
    redis_url: str = "redis://localhost:6379/0"

    # --- embeddings ------------------------------------------------------------
    # 1536, not the LLD's literal 3072 — see docs/DECISIONS.md ADR-004. pgvector's HNSW index
    # has a 2000-dimension ceiling; a vector(3072) column cannot be indexed at all.
    embedding_model: str = "text-embedding-3-large"
    embedding_dimension: int = 1536
    embedding_batch_size: int = 64
    embedding_api_key: str | None = None

    # --- serving mode ----------------------------------------------------------
    serving_mode: str = Field("hosted_baseline", pattern="^(hosted_baseline|tuned_gpu|on_prem)$")

    # --- models ------------------------------------------------------------------
    extract_model: str = "openai/gpt-4o-mini"
    extract_model_tuned: str | None = None
    extract_adapter_id: str | None = None
    verdict_model: str = "openai/gpt-4o"
    classify_model: str = "openai/gpt-4o-mini"
    llm_api_key: str | None = None
    llm_max_retries: int = 2
    llm_timeout_s: int = 60
    llm_breaker_fail_threshold: int = 5
    llm_breaker_reset_s: int = 60

    # --- retrieval -----------------------------------------------------------
    retrieve_vector_k: int = 12
    retrieve_lexical_k: int = 12
    retrieve_final_k: int = 8
    rrf_k: int = 60
    # 2.5, not the LLD's literal 2.0 — see docs/DECISIONS.md ADR-020. At k=60 and weight 2.0,
    # a rank-1-pinned candidate exactly ties a candidate ranked 1 in both other lists.
    rrf_weight_pinned: float = 2.5
    rrf_weight_vector: float = 1.0
    rrf_weight_lexical: float = 1.0
    follow_reference_hops: int = 1
    hnsw_ef_search: int = 120

    # --- extraction ----------------------------------------------------------
    ocr_char_per_page_threshold: int = 120
    classify_confidence_floor: float = 0.70
    span_window_chars: int = 240

    # --- privacy -------------------------------------------------------------
    span_budget_ratio: float = 0.15
    default_retention_days: int = 180

    # --- corpus --------------------------------------------------------------
    corpus_sources_path: str = "app/corpus/corpus_sources.yaml"
    corpus_raw_dir: str = "data/raw/instruments"
    corpus_user_agent: str = "ClauseCheck/1.0 (compliance research)"
    fail_boot_on_pinning_mismatch: bool = True

    # --- concurrency -----------------------------------------------------------
    verdict_model_concurrency: int = 8

    @property
    def is_ci(self) -> bool:
        return self.env == "ci"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
