"""LLD §18: metric names are fixed. This test locks the exact name list so a rename never
slips through unnoticed — a dashboard built against the old name would silently go dark."""

from prometheus_client import generate_latest

from app.obs import metrics

EXPECTED_METRIC_NAMES = {
    "cc_http_requests_total",
    "cc_http_request_duration_seconds",
    "cc_task_duration_seconds",
    "cc_queue_depth",
    "cc_stage_duration_seconds",
    "cc_llm_calls_total",
    "cc_llm_duration_seconds",
    "cc_llm_tokens_total",
    "cc_llm_cost_usd_total",
    "cc_llm_breaker_state",
    "cc_facts_extracted_total",
    "cc_span_grounding_failures_total",
    "cc_span_budget_exhausted_total",
    "cc_verdicts_total",
    "cc_citation_rejected_total",
    "cc_rule_model_divergence_total",
    "cc_conflicts_detected_total",
    "cc_corpus_drift_status",
    "cc_active_snapshot_age_seconds",
}


def test_every_lld_18_metric_name_is_declared():
    rendered = generate_latest(metrics.REGISTRY).decode()
    # Counters/histograms render with a _total/_bucket/_sum/_count suffix; strip to the base
    # name declared in the source (matches what a dashboard query would reference).
    declared = set()
    for line in rendered.splitlines():
        if line.startswith("# HELP "):
            name = line.split()[2]
            if not name.endswith("_created"):  # per-series creation-timestamp metadata
                declared.add(name)
    assert declared == EXPECTED_METRIC_NAMES


def test_citation_rejected_total_increments():
    before = metrics.citation_rejected_total.labels(reason="not_offered")._value.get()
    metrics.citation_rejected_total.labels(reason="not_offered").inc()
    after = metrics.citation_rejected_total.labels(reason="not_offered")._value.get()
    assert after == before + 1


def test_verdicts_total_labels_accept_is_shadow_as_string():
    # Prometheus label values are always strings; booleans must be rendered as "true"/"false"
    # by the caller, not passed through raw (prometheus_client accepts anything str()-able,
    # but a raw bool would render as "True"/"False" — Python's capitalised spelling — which
    # would silently split a metric that's supposed to have exactly two values for this label).
    metrics.verdicts_total.labels(
        verdict="violation", severity="critical", decided_by="rule", is_shadow="true"
    ).inc()
    metrics.verdicts_total.labels(
        verdict="violation", severity="critical", decided_by="rule", is_shadow="false"
    ).inc()
    rendered = generate_latest(metrics.REGISTRY).decode()
    assert 'is_shadow="true"' in rendered
    assert 'is_shadow="false"' in rendered
    assert 'is_shadow="True"' not in rendered
