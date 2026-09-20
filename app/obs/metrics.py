"""Prometheus metrics. LLD §18 — "Metric names are fixed; dashboards and alerts depend on
them." Every metric named in the LLD is declared here, even ones this milestone doesn't wire
up yet (`cc_queue_depth`, `cc_corpus_drift_status`, `cc_rule_model_divergence_total`) — a
dashboard built against the fixed name list should never 404 on a metric that's merely
stuck at zero because nothing increments it yet, only on one that was never declared.
"""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry()

http_requests_total = Counter(
    "cc_http_requests_total",
    "HTTP requests",
    ["method", "route", "status"],
    registry=REGISTRY,
)
http_request_duration_seconds = Histogram(
    "cc_http_request_duration_seconds",
    "HTTP request duration",
    ["method", "route"],
    registry=REGISTRY,
)
task_duration_seconds = Histogram(
    "cc_task_duration_seconds",
    "Celery task duration",
    ["task", "queue", "outcome"],
    registry=REGISTRY,
)
queue_depth = Gauge(
    "cc_queue_depth",
    "Celery queue depth",
    ["queue"],
    registry=REGISTRY,
)
stage_duration_seconds = Histogram(
    "cc_stage_duration_seconds",
    "Pipeline stage duration",
    ["stage"],
    registry=REGISTRY,
)
llm_calls_total = Counter(
    "cc_llm_calls_total",
    "LLM calls",
    ["provider", "model", "stage", "outcome"],
    registry=REGISTRY,
)
llm_duration_seconds = Histogram(
    "cc_llm_duration_seconds",
    "LLM call duration",
    ["provider", "model", "stage"],
    registry=REGISTRY,
)
llm_tokens_total = Counter(
    "cc_llm_tokens_total",
    "LLM tokens",
    ["provider", "model", "stage", "direction"],
    registry=REGISTRY,
)
llm_cost_usd_total = Counter(
    "cc_llm_cost_usd_total",
    "LLM cost in USD",
    ["provider", "model", "stage"],
    registry=REGISTRY,
)
llm_breaker_state = Gauge(
    "cc_llm_breaker_state",
    "LLM circuit breaker state (0 closed, 1 open)",
    ["provider"],
    registry=REGISTRY,
)
facts_extracted_total = Counter(
    "cc_facts_extracted_total",
    "Facts extracted",
    ["doc_type", "field_key"],
    registry=REGISTRY,
)
span_grounding_failures_total = Counter(
    "cc_span_grounding_failures_total",
    "Span grounding failures",
    ["doc_type"],
    registry=REGISTRY,
)
span_budget_exhausted_total = Counter(
    "cc_span_budget_exhausted_total",
    "Span budget exhaustions",
    ["doc_type"],
    registry=REGISTRY,
)
verdicts_total = Counter(
    "cc_verdicts_total",
    "Verdicts issued",
    ["verdict", "severity", "decided_by", "is_shadow"],
    registry=REGISTRY,
)
citation_rejected_total = Counter(
    "cc_citation_rejected_total",
    "Citations rejected by the validator",
    ["reason"],
    registry=REGISTRY,
)
rule_model_divergence_total = Counter(
    "cc_rule_model_divergence_total",
    "Cases where a rule and the model would have disagreed",
    ["rule_id"],
    registry=REGISTRY,
)
conflicts_detected_total = Counter(
    "cc_conflicts_detected_total",
    "Cross-document conflicts detected",
    ["group_key", "conflict_type"],
    registry=REGISTRY,
)
corpus_drift_status = Gauge(
    "cc_corpus_drift_status",
    "Corpus drift status (0 unchanged, 1 changed, 2 unreachable)",
    ["instrument_code"],
    registry=REGISTRY,
)
active_snapshot_age_seconds = Gauge(
    "cc_active_snapshot_age_seconds",
    "Age of the active corpus snapshot in seconds",
    registry=REGISTRY,
)
