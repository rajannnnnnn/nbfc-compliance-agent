"""(stage, mode) -> model config. HLD §7.4: three serving modes, only hosted_baseline
attempted live in this session (see ADR-021)."""

from dataclasses import dataclass

from app.config import Settings


@dataclass(frozen=True)
class ModelConfig:
    model: str
    adapter_id: str | None = None


def route(stage: str, settings: Settings) -> ModelConfig:
    if stage == "extract":
        if settings.serving_mode == "hosted_baseline":
            return ModelConfig(model=settings.extract_model)
        return ModelConfig(
            model=settings.extract_model_tuned or settings.extract_model,
            adapter_id=settings.extract_adapter_id,
        )
    if stage == "classify":
        return ModelConfig(model=settings.classify_model)
    if stage == "verdict":
        # Verdict always runs on the hosted frontier model regardless of serving_mode
        # (HLD §7.1: "Fine-tuning a small model for legal reasoning ... buys little").
        return ModelConfig(model=settings.verdict_model)
    raise ValueError(f"unknown stage: {stage}")
