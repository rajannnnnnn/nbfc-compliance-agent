# CLAUDE.md — ClauseCheck agent operating rules

> **Filename is fixed by tooling.** Claude Code auto-loads `CLAUDE.md` from the
> repository root. Do not rename it to match the other documents in this set.

Read this before touching code. `ClauseCheck_LLD_v1.0.md` is the authority on *what*
to build. This file is the authority on *how to behave while building it*.

Document set:

| File | Role |
|---|---|
| `ClauseCheck_PRD_v1.0.md` | Product Requirements Document — problem, users, scope, success criteria |
| `ClauseCheck_HLD_v1.0.md` | High-Level Design — architecture, corpus model, stage responsibilities |
| `ClauseCheck_LLD_v1.0.md` | Low-Level Design — DDL, models, signatures, prompts, algorithms, contracts |
| `CLAUDE.md` | This file — agent operating rules |
| `ClauseCheck_Build_Kickoff_Prompts_v1.0.md` | Prompts used to drive the build |

---

## 1. The system in one paragraph

ClauseCheck is a retrospective compliance auditor for Indian NBFCs. A lender's own
compliance team submits loan documents and collections-call transcripts. The system
extracts typed facts, resolves which RBI provisions were in force on the date of the
event being judged, retrieves the governing clauses, and issues a cited verdict of
`compliant`, `violation`, `ambiguous`, or `no_clause_found`. It is not borrower-facing,
not a decisioning system, and not in any credit or payment hot path.

## 2. Non-negotiables

Invariants. If a task appears to require breaking one, stop and say so instead of
working around it.

1. **No verdict without a resolvable citation.** Every citation must resolve to a
   `clause` row whose effective window contains the event date. Enforced by
   `app/verdict/validator.py`, in code, not by prompt instruction. A model response
   failing validation becomes `no_clause_found` and is logged; it is never passed
   through.
2. **Facts never carry judgements.** Stage A emits what a document *says*. Legality is
   decided in Stage C over retrieved clauses. An `is_violation` or `severity` field on
   an extracted fact means the architecture is broken.
3. **No document bytes persisted.** Not in Postgres, not on disk, not in object storage,
   not in a log line, not in a Celery payload. What persists: SHA-256 of the input, the
   tenant's own source URI, typed normalised values, and PII-redacted quoted spans
   capped at 15% of source characters.
4. **No real borrower data in this repository.** Every fixture, demo document and eval
   case is synthetic, carries `is_synthetic = true`, and renders with a visible banner.
5. **Corpus is versioned and hash-pinned.** Clause text enters only through the ingest
   pipeline, which records source URL, retrieval timestamp and SHA-256. Nobody hand-edits
   clause text; fix the parser and re-ingest.
6. **Never invent a clause identifier.** RBI instruments in this family do not use
   decimal numbering. `DL2025/p9/ii` is real; `DL2025/Ch.IV/4.2(a)` is not. If a path is
   absent from the ingested corpus, it does not exist.
7. **Effective dates are load-bearing.** Retrieval without an `as_of` date raises. There
   is no default. A 2026 event must never be judged under a 2027 clause.

## 3. Stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.11 | Pinned in `pyproject.toml` and Dockerfile |
| API | FastAPI + Uvicorn | Async; all long work goes to the queue |
| Validation | Pydantic v2 | Every stage boundary is a model, never a dict |
| ORM / migrations | SQLAlchemy 2.0 async + Alembic | No `create_all` outside tests |
| Database | PostgreSQL 16 + pgvector | Vector dimension from config, never hardcoded |
| Queue | Celery 5 + Redis 7 | Redis is broker/result only, never a datastore of record |
| LLM routing | LiteLLM | No provider SDK imported outside `app/llm/` |
| Local inference | vLLM | Dev and on-prem only; not required for hosted deploy |
| Tests | pytest, pytest-asyncio, testcontainers | Integration tests use real Postgres, not SQLite |
| Load | k6 | Scripts in `loadtest/` |
| Quality | ruff, black, mypy (strict on `app/`) | Enforced pre-commit and in CI |

## 4. Commands

`make` is the entry point. Create a target as part of the first task that needs it.

```
make dev            # docker compose up: postgres, redis, api, worker
make migrate        # alembic upgrade head
make revision m=".."# autogenerate a migration
make ingest         # fetch + parse + chunk + embed the regulation corpus
make corpus-verify  # re-fetch sources, compare hashes, report drift, mutate nothing
make test           # unit + integration
make test-unit      # pytest -m "not integration"
make eval suite=..  # run an eval suite, write reports/eval_<ts>.json
make eval-report    # render latest eval run as markdown
make lint           # ruff + black --check + mypy
make load           # k6 run loadtest/baseline.js
make seed-demo      # load synthetic demo accounts
```

## 5. How to work

**Read before writing.** This codebase has deliberate seams — stage boundaries, the LLM
client, the validator. Code that bypasses a seam gets reverted even when it works.

**One migration per schema change, always reversible.** Write and test `downgrade()`.

**Tests ship with the task.** A task is done when it has tests that would fail against
the previous commit. For extraction, retrieval or verdict work that means at least one
eval case in `eval/cases/`, not only a unit test.

**Deterministic before probabilistic.** If a check is expressible as a rule over typed
facts, write the rule. Rules in `app/rules/` are pure, synchronous and testable with no
network. Send to a model only what needs language understanding.

**No agents, no open-ended tool loops.** Control flow is explicit. Re-retrieval on
conflict is a deterministic trigger, not a planner. A task that sounds like it wants an
autonomous agent wants a rule — re-read the LLD.

**Prompts live in versioned files**, `app/prompts/<stage>/<name>.v<N>.md`. Bump `N` for
any change. The version is recorded on every assessment. Editing a prompt in place
without a bump makes every historical result unreproducible.

**Cost and latency are recorded, not estimated.** Every model call records provider,
model id, adapter id, tokens in, tokens out, wall-clock ms and computed cost.

**Log structured, log no content.** `structlog` JSON. Ids, counts, durations, hashes,
verdicts, clause paths — yes. Document text, extracted values, borrower names, prompt
bodies — never.

## 6. Git

Branch per task: `feat/<slug>`, `fix/<slug>`, `chore/<slug>`. Conventional commits.
Small commits with passing tests beat one large commit. Never commit `.env`,
credentials, fetched PDFs, model weights, adapter files, `reports/`, or `data/raw/`.
Check `git status` before staging; no blind `git add -A`. Do not rewrite published
history.

## 7. Definition of done

1. Code written, typed, lint-clean.
2. Migration with tested `downgrade()`, if schema changed.
3. Unit and integration tests pass against real Postgres and Redis.
4. For extraction / retrieval / verdict changes: eval run executed, numbers in
   `reports/`, delta against the previous run stated in the task summary.
5. No non-negotiable from §2 violated.
6. `README.md` updated if user-visible behaviour changed.

## 8. When uncertain about the regulation

Do not guess clause numbers and do not invent clause text. The corpus is the only source
of truth about what a clause says. The PRD and HLD record which regulatory facts are
verified against an RBI-hosted source and which are not. If a task depends on an
unverified fact, implement it behind a corpus lookup so it self-corrects on re-ingest,
and flag the dependency in your summary. Writing a plausible-sounding clause reference
into this codebase is the worst thing you can do to it.
