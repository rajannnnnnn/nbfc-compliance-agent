# Metrics tracking — ClauseCheck

Living record of product metrics (PRD §8.1), what's driving each number, and every
measurement attempt. Append a new dated entry under **History** every time a suite is
re-run live after a real change — never overwrite a past entry. This file is the source of
truth for "are we improving," not chat scrollback.

## 1. Current metrics table

| # | Metric | Target (v1) | Measured | Status | What's influencing it | Business impact |
|---|---|---|---|---|---|---|
| 1 | Extraction exact-match | ≥90% | 82.5% (`extraction_core`, 100 cases) | ❌ | `app/extract/*` value-extraction prompt/model — not yet root-caused | Wrong facts silently poison downstream verdicts |
| 2 | Span-grounding rate | ≥99% | 48.6% (`extraction_core`) / 43.3% (`adversarial`) | ❌ Worst gap | `app/extract/*` quoted-span capture specifically (value accuracy is much higher than span accuracy on the same cases) | Core trust promise ("here's the exact quote") fails over half the time |
| 3 | Retrieval recall@4 | ≥95% | Untested — `retrieval` suite has 0 cases | ⚠️ | `app/retrieve/*` (vector ANN + lexical FTS + RRF) | Unknown ceiling on every downstream verdict metric |
| 4 | Applicability precision | 100% | Untested, 1 confirmed live leak (`EV-TEMPORAL-009`) | ⚠️ | `app/retrieve/applicability.py` effective-date filter | A leak here = citing a law that wasn't in force — real liability exposure |
| 5 | Numeric-rule verdict accuracy | ≥99% | **100%** (49 cases live, incl. real RBC2025 text) | ✅ | `app/rules/*` deterministic code | Real, working, sellable claim today |
| 6 | Hallucinated citation rate | exactly 0 | **0.0** everywhere measured | ✅ | `app/verdict/validator.py` | Biggest competitive claim in the PRD, and it's real |
| 7 | Abstention correctness | ≥90% | 82.5% (40 cases live) | ❌ | Confirmed split: `app/retrieve/*` surfaces real-but-irrelevant clauses + `app/verdict/assess.py` model fallback isn't skeptical enough | PRD's #1 trust property; false confidence is worse than silence |
| 8 | Latency p95 | <10s | Untracked — no load test run | ⚠️ | Unidentified | Release gate #1 requirement, unverified |
| 9 | Cost per document | Tracked & published | Untracked | ⚠️ | `StageTelemetry` captures it already; aggregation/publishing missing | Can't price/sell the product without this |
| 10 | Judgment-verdict accuracy *(proposed, not official PRD metric)* | — | **31.25%** (16 cases live) | ❌ Worst overall | Confirmed 6:5 split: `app/retrieve/*` (5/11, clause never surfaced) + `app/prompts/verdict/*`/model (6/11, correct clause retrieved, model still won't commit) | This is the actual product; most real audits today would get a wrong verdict |

**Cross-cutting**: `app/retrieve/*` is a contributing cause in 4 of 5 failing/unmeasured rows (#3, #4, #7, #10) — the most repeated root cause on the sheet.

## 2. Data completeness checklist (separate from metrics — this is corpus/fixture coverage)

- [x] Harness/infra: Postgres+pgvector, Redis, migrations, all 7 eval suites — proven live, zero blockers
- [x] `RBC2025` real text ingested (211 clauses, 0 parser warnings) — still `verification_status: unverified` pending sign-off or a live `rbi.org.in` fetch
- [ ] `DL2025` — no real source found yet (backs the most rules: R09, R10, R14, R23, cooling-off)
- [ ] `KFS2024` — fully placeholder
- [ ] `RBC-AMD2026` / `RBC-AMD2026-DRAFT` — fully placeholder
- [ ] Synthetic loan-document fixtures covering **all** scenarios (compliant, violation, ambiguous, no-clause, adversarial/OCR-noise, conflicting-documents, temporal-edge) — partially exists in `eval/cases/*` but not organized as a standalone reusable fixture set outside the harness

## 3. History

### 2026-09-21 — Session baseline (this session)

**Infra work**: Installed Postgres 16 + pgvector + Redis directly via `apt` (Docker Hub image
pulls are policy-blocked in this sandbox's network proxy). Ran all 10 Alembic migrations.
Ran `make ingest` live. Ran all 7 eval suites live for the first time this session — found
and fixed a real teardown bug (`audit_event` FK violation in `eval/runner.py`), found and
fixed a real case-design bug in `EV-E2E-0001`, corrected a wrong PDF-to-instrument mapping
for `RBC2025` and ingested its real text (211 clauses, 0 warnings).

**Measurements** (all commits referenced are on `claude/session-specs-0069s6`):

| Suite | Result | Commit |
|---|---|---|
| `conflicts` | 1.0 / 1.0 (8/8) | pre-existing, reconfirmed |
| `numeric_rules` | 1.0 verdict_accuracy, 0.0 hallucination (49/49) | reconfirmed after real RBC2025 swap — unchanged |
| `temporal` | 1.0 verdict_accuracy, 0.667 citation_validity (14 cases) | first live run this session |
| `abstention` | 0.825 (33/40) | first live run this session |
| `end_to_end` | 1.0 / 1.0 (1/1) after fixing 2 real bugs | ADR-052/053 |
| `verdict` | **0.3125** (5/16) | ADR-054 — reconfirms a pre-existing ~0.25 finding, not a regression |
| `adversarial` | 5/8 passed, field_accuracy 0.929, **span_grounding 0.433**, found a reproducible 100x currency-scaling bug | ADR-054 — first live run ever |
| `extraction_core` | field_accuracy 0.825, span_grounding 0.486 (100 cases) | pre-existing data (2026-09-20), reconfirmed present |

**Root-cause work done**: split `verdict`'s 11 failures into 6 judgment-caused vs. 5
retrieval-caused (see table above). Found `abstention`'s failure mode is retrieval surfacing
real-but-irrelevant clauses, not hallucination. Found `temporal`'s one forbidden-citation
leak (`EV-TEMPORAL-009`).

**Not attempted yet**: no code change made to `app/retrieve/*`, `app/extract/*`, or
`app/prompts/verdict/*` this session — this entry is a measurement/diagnosis baseline, not
an improvement attempt. The 100x currency bug and the temporal leak are both concrete,
reproducible, and root-causable; neither has been fixed yet.

**Confidence**: infra/harness — high, proven solid. Product accuracy — real, unresolved gaps
on 6 of 10 metrics. Next entries in this file should be actual fix attempts with before/after
numbers, not more diagnosis.
