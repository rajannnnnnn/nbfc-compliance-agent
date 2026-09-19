# ClauseCheck — Document Set v1.0

RBI-grounded lending compliance auditor for Indian NBFCs. Handoff package for build.

**Owner** N Rajan · **Date** 19 September 2026 · **Status** approved for build

## Documents, in reading order

| # | File | Document type | Audience | Length |
|---|---|---|---|---|
| 1 | `ClauseCheck_PRD_v1.0.md` | Product Requirements Document | Executive, product, interviewers | ~3,500 words |
| 2 | `ClauseCheck_HLD_v1.0.md` | High-Level Design / architecture | Engineering leadership, reviewers | ~4,000 words |
| 3 | `ClauseCheck_LLD_v1.0.md` | Low-Level Design / implementation specification | The implementing engineer or agent | ~12,000 words |
| 4 | `CLAUDE.md` | Agent operating rules | The coding agent (auto-loaded) | ~1,200 words |
| 5 | `ClauseCheck_Build_Kickoff_Prompts_v1.0.md` | Build handoff prompts | The engineer driving the build | ~1,400 words |

`CLAUDE.md` keeps that exact filename because Claude Code auto-loads it from the repository
root. Everything else follows the `ClauseCheck_<TYPE>_v<version>.md` convention.

## How to use this package

1. Copy all five files into an empty repository root.
2. Paste **Prompt 1** from the kickoff document into Claude Code.
3. The agent writes `TASKS.md`, reports its disagreements with the specification, and stops.
4. Reply, and it begins M1 — the regulation corpus, which comes first because every other
   component's correctness is defined relative to it.

## What each document settles

**PRD** — the problem, the two user personas, the jobs to be done, scope and non-goals, the
competitive position, the measured success criteria, the six-item release gate, the
regulatory scope with per-instrument verification status, the defining behaviour, the nine
milestones, and the principal risks.

**HLD** — the three-stage architecture and why it is not a monolith, stage responsibilities,
the clause-identity and temporal model, the corpus ingest and versioning approach, the rule
and conflict-detection strategy, model-layer division of labour with the serving constraint,
data posture, tenancy, evaluation architecture, deployment topology, and twelve architectural
decisions of record.

**LLD** — module map with the dependency rule, every configuration key, full DDL with enums
indexes and row-level security, domain models, the field registry format and all 61 keys, the
corpus parser and chunker algorithms, the pinning table, retrieval SQL and fusion arithmetic,
the three prompts verbatim, the citation validator in full, the rule interface with two rules
implemented, the conflict detector, redaction patterns, Celery task signatures, API contracts
with real payloads, the error taxonomy, evaluation metric formulas, metric names, test
obligations per module, both environments, and the task breakdown with runnable acceptance
criteria.

## Three facts that shaped this design

The recovery-conduct amendment is **notified, not draft** — issued 6 August 2026, effective
1 January 2027. The corpus therefore holds four concurrent temporal layers and every
retrieval is scoped to the event date. This is the system's defining feature, not a detail.

RBI instruments in this family use **continuous paragraph numbering, not decimal clause
numbering**. Clause paths look like `DL2025/p9/ii`, never `DL2025/Ch.IV/4.2(a)`. The earlier
scheme would have produced citations that do not resolve, which in this system is the only
unrecoverable defect.

**Per-token serving of custom LoRA adapters has largely left the market.** The design names
three serving modes and records which produced every result, rather than claiming a
fine-tune serves the always-on demonstration.
