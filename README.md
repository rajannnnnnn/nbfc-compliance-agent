# ClauseCheck

RBI-grounded lending compliance auditor for Indian NBFCs.

**Owner** N Rajan · **Date** 19 September 2026 · **Status** building against `TASKS.md`

## Build status

Code is under active build against the LLD. Progress, milestone by milestone, is tracked in
`TASKS.md`. Every point where the specification was ambiguous, inconsistent, or silent is in
`docs/SPEC_QUERIES.md`; the resolution actually built is recorded as an ADR in
`docs/DECISIONS.md` — read that before either of the others if you only have time for one.

## Bringing your own RBI corpus

This repository does not ship real RBI regulatory text. `app/corpus/corpus_sources.yaml`
points at local files under `data/raw/instruments/`; see
`data/raw/instruments/README.md` for the exact format. Until real source documents are placed
there, the system runs against clearly-labelled placeholder text (`verification_status:
unverified`), which puts every rule in shadow mode automatically — it computes and is
measured, but never emits a citable finding. See `docs/DECISIONS.md` ADR-001.

To go live: replace the files in `data/raw/instruments/`, set each instrument's
`verification_status` honestly in `corpus_sources.yaml`, then:

```bash
make ingest          # parses, chunks, embeds, activates a new snapshot; writes docs/CORPUS.md
make corpus-verify   # re-fetches sources, reports drift, mutates nothing
```

## Quickstart (local, no Docker required)

```bash
pip install -e ".[dev]"
cp .env.example .env                    # fill in CC_LLM_API_KEY / CC_EMBEDDING_API_KEY when ready

# Postgres 16 + pgvector + Redis, if not already running (apt path — works even where
# Docker image pulls are blocked, e.g. a locked-down sandbox; `make dev` below is the
# normal path when Docker is available):
sudo apt-get install -y postgresql-16 postgresql-16-pgvector redis-server
sudo service postgresql start && redis-server --daemonize yes

sudo -u postgres createdb <your-db>
sudo -u postgres psql -d <your-db> -c "CREATE EXTENSION IF NOT EXISTS vector;"
sudo cp scripts/tsearch/numbers.syn "$(pg_config --sharedir)/tsearch_data/numbers.syn"  # required before the next step — db_bootstrap.sql creates a text-search dictionary that reads this file
sudo -u postgres psql -f scripts/db_bootstrap.sql -d <your-db>

alembic upgrade head
make test-unit                          # no external services needed
CC_ENV=ci make test-integration         # needs Postgres + Redis reachable at CC_DATABASE_URL / CC_REDIS_URL
uvicorn app.main:app --reload           # http://localhost:8000/healthz, /readyz, /v1/corpus
```

Or via Docker Compose: `make dev` (preferred when Docker image pulls aren't blocked by your
network policy).

---

# Document Set v1.0

The original handoff package this build was driven from. Kept for reference — everything it
describes is now either built (see `TASKS.md`) or explicitly deferred with a reason.

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
