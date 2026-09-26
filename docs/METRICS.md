# Product Metrics — NBFC Compliance Intelligence (ClauseCheck)

> **Purpose.** One place that tracks every metric that bears on product quality, reliability,
> and cost — logged with a date on every measurement, never overwritten. Each cycle, re-run the
> commands in [How to regenerate](#how-to-regenerate-each-cycle), append a new dated entry to
> [§7 Changelog](#7-changelog-append-only), and update the "Current" column in each table below.
> Targets are revised only when a metric is actually hit or a real constraint changes — not on
> a schedule.
>
> **Ground rule.** Every number in this document is either read directly from a committed eval
> report (`reports/eval_*.json`, gitignored but reproducible via `make eval`), from a passing
> test run, or from `git log`. Where no real measurement exists yet, the row says **not yet
> measured** rather than a guessed number. This document does not fabricate metrics that
> "sound plausible" — CLAUDE.md §8's rule against inventing regulatory facts applies with equal
> force to inventing performance facts.

---

## 1. Verdict-stage quality (the core promise: cited, correct, non-hallucinated verdicts)

Source: `reports/eval_{verdict,abstention,temporal,numeric_rules}_latest.json`

| Metric | Current | Date measured | Cases (N) | Next-cycle target | Steady-state target |
|---|---|---|---|---|---|
| **Citation validity** (verdict suite) | **100%** | 2026-09-21 | 16 | maintain 100% | 100% (hard guarantee, §2 CLAUDE.md — any regression here is release-blocking) |
| **Hallucinated citation rate** | **0%** | 2026-09-21 | 16 | maintain 0% | 0% (hard guarantee — the validator makes this structurally impossible, not aspirational) |
| **Verdict accuracy — `verdict` suite** | **31.25%** ⚠️ | 2026-09-21 (stale — 5 days old, predates this session's 3 backend fixes) | 16 | **70%** | 90%+ |
| **Abstention correctness** (`abstention` suite) | **100%** | 2026-09-26 | 40 | maintain 100% | 100% |
| **False violation rate** (`abstention` suite) | **0%** | 2026-09-26 | 40 | maintain 0% | 0% |
| **Verdict accuracy — `temporal` suite** | 100% verdicts, but 3/14 missed a `context_citations` entry | 2026-09-26 | 14 | fix the 3 missed context citations | 0 missed context citations |
| **Verdict accuracy — `numeric_rules` suite** | **100%** | 2026-09-26 | 49 | maintain 100% | 100% |
| **Conflict detection accuracy** | **100%** | 2026-09-26 | 8 | grow case count to ≥30 before trusting this number | 100% at N≥50 |
| **`raises_check` accuracy** | **100%** | 2026-09-26 | 8 | grow case count | 100% at N≥50 |

**Read this table honestly:** the 31.25% verdict-suite number is the single worst number in this
document and the one that matters most — it means most non-trivial verdicts (not abstentions,
not pure numeric-rule cases) are currently wrong. It has **not been re-run since 2026-09-21**,
so it predates the lexical-retrieval crash fix, the cross-event-loop fix, and the concurrency
fix landed this session (2026-09-26) — some, possibly much, of this failure rate may already be
resolved by fixes those cases never saw. **Action item for next cycle: re-run `make eval
suite=verdict` before any further extraction/verdict work, so effort isn't spent chasing a
number that's already stale.**

---

## 2. Extraction-stage quality (Stage A: does it pull the right typed facts?)

Source: `reports/eval_extraction_core_latest.json`, `reports/eval_adversarial_latest.json`

| Metric | Current | Date measured | Cases (N) | Next-cycle target | Steady-state target |
|---|---|---|---|---|---|
| **Field accuracy** (`extraction_core`) | **82.5%** | 2026-09-20 | 125 | 90% | 95%+ |
| **Absence accuracy** (`extraction_core`) | **93.3%** | 2026-09-20 | 125 | 96% | 98%+ |
| **Span grounding** (`extraction_core`) | **48.6%** ⚠️ | 2026-09-20 | 125 | 75% | 90%+ |
| Field accuracy (`adversarial`, small N) | 92.9% | 2026-09-21 | 8 | maintain, grow N | 95%+ at N≥40 |
| Absence accuracy (`adversarial`) | 96.8% | 2026-09-21 | 8 | maintain, grow N | 98%+ at N≥40 |
| Span grounding (`adversarial`) | 43.3% ⚠️ | 2026-09-21 | 8 | 75% | 90%+ |

**Span grounding at ~48%** means barely half of correctly-extracted facts have a
verifiable, literal quoted span back to the source document. Given CLAUDE.md §2's non-negotiable
that persisted spans must be real, grounded quotes (never paraphrase), this is the second most
urgent number in this document — it's a data-quality risk sitting quietly under a 82.5% headline
field-accuracy number that looks fine on its own.

**Weakest individual fields** (from `extraction_core`, real per-field breakdown, sorted worst-first):

| Field | Exact match | Absence accuracy |
|---|---|---|
| `contact_datetime` | **0%** | **0%** |
| `recovery_agent_identity_notified_before_contact_flag` | 32% | 100% |
| `agent_id_disclosed_flag` | 32% | 100% |
| `call_recorded_flag` | 32% | 100% |
| `kfs_validity_days` | 60% | 60% |
| `sanctioned_amount` | 62% | 76% |
| `fees_total` | 66% | 80% |
| `interest_rate_bps` | 72% | 72% |

`contact_datetime` at a flat 0% is not a rounding artifact — it means this field is currently
**never** extracted correctly in the eval suite. That is the single most concrete, well-defined
next task this document surfaces: **fix `contact_datetime` extraction before touching anything
else in Stage A.**

---

## 3. Retrieval-stage quality (Stage B: does it find the right clauses?)

**Not yet instrumented.** `eval/metrics.py` says so explicitly in its own docstring
("Retrieval-stage metrics are not implemented — no `retrieval` suite cases exist yet"), and
`eval/cases/retrieval/` is empty. There is no real MRR, recall@k, or precision@k number to
report — anything printed here today would be invented, which is exactly what this document
promises not to do.

| Metric | Current | Next-cycle target |
|---|---|---|
| MRR@5 (lexical) | not yet measured | write ≥20 retrieval cases, get a first real number |
| MRR@5 (vector) | not yet measured | same |
| MRR@5 (fused/RRF) | not yet measured | same |
| Recall@10 (fused) | not yet measured | same |

**Action item for next cycle:** build `eval/cases/retrieval/*.json` (field/value → expected
top-k clause paths, mirroring the existing `test_lexical_numeric_recall.py` integration test
cases, which already prove real retrieval behavior but aren't wired into the eval harness's
metrics) and implement the metric functions in `eval/metrics.py`. Once a first real MRR/recall
number exists, this table gets its first target *derived from that number*, not guessed now.

---

## 4. Reliability — production incidents this development cycle

This is a real, dated incident log from this session, each row tied to a commit. Unlike the
eval numbers above, these are not sampled — they are the complete list of confirmed
production-breaking defects found and fixed since deployment began.

| # | Date/time (UTC) | Incident | Root cause | Fix commit |
|---|---|---|---|---|
| 1 | 2026-09-26 ~09:00 | Every request 401 | Truncated `api_key_hash` in prod DB (CHAR column padding) | (DB UPDATE, not a commit) |
| 2 | 2026-09-26 07:49 | Gateway 422 on every route | Untyped lambda route handler | `9a061d1` |
| 3 | 2026-09-26 09:41 | Backend could die silently behind a "healthy" gateway | No process-supervision — one child dying didn't stop the container | `ba88d36` |
| 4 | 2026-09-26 11:28 | Assessment latency scaled linearly with fact count, exceeding the frontend's poll budget | Sequential per-fact embed+verdict calls in `assess.document` | `272dd86` |
| 5 | 2026-09-26 11:54 | **Every** assessment failed outright on production Postgres (Neon) | Lexical retrieval hardcoded a text-search config (`clausecheck_en`) that only migration-installs on self-hosted Postgres with filesystem access | `56a460c` |
| 6 | 2026-09-26 12:10 | Second-and-later Celery task in a worker process crashed | Module-global DB engine/pool reused pooled asyncpg connections across separate `asyncio.run()` event loops | `64d6628` |

**Reliability read:** 6 confirmed, independent, production-affecting defects in one deployment
cycle, found via a mix of production log analysis and local reproduction (not guesswork —
incidents 5 and 6 were each reproduced locally with a harness that matched the exact failure
signature before being called "fixed"). This is a **new, unproven deployment** — a low defect
*count* here is not yet evidence of reliability; the meaningful signal will be the defect rate
over the **next** cycle, after this batch is deployed and given real traffic.

| Reliability metric | Current | Next-cycle target |
|---|---|---|
| Confirmed production incidents, this cycle | 6 | 0 new incidents in the next 7 days of live use |
| Incidents reproduced locally before being called fixed | 2 of 6 (the two most recent; earlier ones were fixed from log evidence without a full local repro harness) | 100% — every future fix reproduced locally first |
| Mean time from report to fix (this cycle, rough) | same-session (minutes to ~1 hour) | maintain |

---

## 5. Test & code quality

Measured directly, 2026-09-26, this session:

| Metric | Current | Next-cycle target |
|---|---|---|
| Unit tests (`pytest -m "not integration"`) | **241/241 passed** | keep at 100%; grow suite size, not just pass rate |
| Integration tests, `tasks` + `retrieve/lexical` (the two areas touched by incidents 5–6) | **13/13 passed** | 100%, plus add retrieval-metric tests once §3 lands |
| Full integration suite | 86 passed / 6 failed | investigate and fix the 6 — see note below |
| `ruff` | clean | maintain |
| `black --check` | clean | maintain |
| `mypy --strict` on `app/` | 2 pre-existing errors (`app/verdict/state.py:85,92`, missing var annotations — predate this cycle, confirmed via `git stash`) | **0 errors** |

**Note on the 6 full-suite failures:** all 6 (4 in `test_rls.py`, 1 in `test_reference_hop.py`,
1 in `test_retrieve_service.py`) were confirmed via `git stash` to fail identically with and
without this cycle's code changes. The `test_rls.py` failures are a **local sandbox artifact**
(an ad-hoc `ALTER DATABASE ... OWNER TO cc_app` grant made during setup, which bypasses
row-level security by table ownership — not a code defect). The other two are unexplained and
carried over as a genuine open item, not dismissed:

| Open test failure | Status |
|---|---|
| `test_reference_hop.py::test_kfs_completeness_reaches_kfs_annex_via_incorporates_edge` | Unresolved — needs investigation next cycle |
| `test_retrieve_service.py::test_microfinance_clause_excluded_for_general_borrower` | Unresolved — needs investigation next cycle |

---

## 6. Performance & cost

| Metric | Current | Date measured | Next-cycle target |
|---|---|---|---|
| Per-fact assessment latency, sequential (pre-fix) | 33.8s for 8 facts / 9 checks (simulated 1.2s embed + 3.0s verdict latency) | 2026-09-26, local repro | n/a — superseded |
| Per-fact assessment latency, concurrent (post-fix, concurrency=4) | **8.6s** for the same 8 facts / 9 checks (~4x) | 2026-09-26, local repro | measure the **real** number against live Gemini latency, not simulated |
| End-to-end assessment latency, live production | **not yet measured** — no successful live run has been confirmed as of this writing | — | get one clean live run, then establish p50/p95 |
| Cost per assessment (`cost_usd`, tracked in code via `llm_cost_usd_total`) | not yet aggregated/reported | — | establish a baseline aggregate once live traffic exists |
| API `p95` latency (`/v1/loans/*`) | not yet measured (no dashboard wired to the Prometheus metrics `app/obs/metrics.py` already emits) | — | wire a dashboard, or at minimum a `make metrics-report` puller |

---

## 7. Changelog (append-only — never edit a past entry, only add new ones)

### 2026-09-26 — Cycle 1 (baseline)
- First version of this document. All numbers above are the actual current state as of this
  date, pulled from real eval reports and real test runs, not estimates.
- Headline risks flagged: `verdict` suite accuracy (31.25%, stale), `span_grounding` (~48%),
  `contact_datetime` field (0% exact match), retrieval-stage metrics entirely unimplemented.
- 6 production incidents found and fixed this cycle (see §4). Deployment is new; reliability
  claims should be re-assessed after a real observation window, not from this cycle's fix count
  alone.

---

## How to regenerate each cycle

```bash
make eval suite=verdict        # re-run the stale 31.25% number first — highest priority
make eval suite=abstention
make eval suite=temporal
make eval suite=numeric_rules
make eval suite=conflicts
make eval suite=adversarial
make eval suite=extraction_core
make eval suite=end_to_end
make eval-report                # renders the latest run of each suite as markdown

make test                       # full pytest — unit + integration
make lint                       # ruff + black --check + mypy
```

Then: read each `reports/eval_<suite>_latest.json`, update the "Current" column in the relevant
table above, and append a new dated entry under §7 — do not overwrite Cycle 1.
