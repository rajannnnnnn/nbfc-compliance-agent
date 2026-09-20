# ClauseCheck — Task Breakdown

Expansion of `ClauseCheck_LLD_v1.0.md` §21 into ordered, individually shippable tasks.

Authority: the LLD is what to build; `CLAUDE.md` is how to build it. Where this file and the
LLD disagree, the LLD wins and this file is wrong — except where a task is annotated
**[SPEC]**, which marks a point where the specification is internally inconsistent or
unimplementable as written and a decision is required before the task can be closed. Those
are listed in full in `docs/SPEC_QUERIES.md` and are open until answered.

## How to read a task

Every task carries **Depends on**, **Files**, and **Acceptance**. Acceptance is a command or
a test. A criterion that cannot be executed is not an acceptance criterion and does not
appear here. `pytest` node ids are written as they will exist; a task is not done until its
node id runs green from a clean checkout.

## Conventions binding on every task

- Branch per task, `feat/<slug>` / `fix/<slug>` / `chore/<slug>`, conventional commits
  (`CLAUDE.md` §6). *Note: this session is constrained to push to `claude/session-specs-0069s6`;
  per-task branching resumes once that constraint lifts.*
- Definition of done is `CLAUDE.md` §7 in full, not just the acceptance line below.
- Every task that changes extraction, retrieval or verdict behaviour ships at least one case
  in `eval/cases/`, not only a unit test.
- Non-obvious choices are recorded in `docs/DECISIONS.md` as a short ADR before the task closes.
- `make lint` (ruff + black --check + mypy strict on `app/`) passes on every commit.

## Status legend

`open` · `in-progress` · `blocked` · `done`

---

# M0 — Repository scaffolding *(added; not in LLD §21)*

LLD §21 begins at `corpus_sources.yaml`, but every M1 task presumes an installable Python
package, a Makefile, and a container. That scaffolding has no owning task in the LLD, so it
is given one here rather than smuggled into M1-T01.

### M0-T01 — Project skeleton and tooling
- **Status** done
- **Depends on** —
- **Files** `pyproject.toml`, `Makefile`, `.gitignore`, `.env.example`, `.pre-commit-config.yaml`, `app/__init__.py`
- **Acceptance**
  ```bash
  python -c "import sys; assert sys.version_info[:2]==(3,11)"
  pip install -e ".[dev]" && make lint          # ruff, black --check, mypy strict on app/
  git check-ignore -q .env data/raw reports && echo "ignored"
  ```
  `.gitignore` must cover `.env`, `data/raw/`, `reports/`, `*.pdf`, adapter artefacts
  (`CLAUDE.md` §6).

### M0-T02 — `app/config.py` Settings
- **Status** done — `tests/unit/test_config.py`, 6/6 passing
- **Depends on** M0-T01
- **Files** `app/config.py`, `tests/unit/test_config.py`
- **Acceptance**
  ```bash
  pytest tests/unit/test_config.py -q
  ```
  Asserts: `extra="forbid"` rejects an unknown `CC_*` var; `env` rejects a value outside
  `local|ci|prod`; `serving_mode` rejects a value outside the three modes; a missing
  `database_url` raises; `get_settings()` is cached (same object on two calls). Every key in
  LLD §2 is present with the specified default.
  **[SPEC]** `extract_model`, `verdict_model` and `classify_model` default to the literal
  placeholders `<frontier-model-id>` / `<small-model-id>`; real ids required — see SQ-11.

### M0-T03 — Docker Compose and the `cc_app` role
- **Status** done — grants moved to migration 0008 per ADR-008; verified against real Postgres 16 + pgvector 0.6
- **Depends on** M0-T01
- **Files** `Dockerfile`, `docker-compose.yml`, `scripts/db_bootstrap.sql`, `Makefile`
- **Acceptance**
  ```bash
  make dev && docker compose ps --format json | jq -e 'all(.Health=="healthy" or .State=="running")'
  psql "$CC_DATABASE_URL" -c "SELECT extname FROM pg_extension WHERE extname IN ('vector','pg_trgm')" | grep -c . 
  psql -U postgres -c "SELECT rolbypassrls FROM pg_roles WHERE rolname='cc_app'" | grep -q f
  ```
  **[SPEC]** LLD §20.1 grants `ON ALL TABLES IN SCHEMA public` at bootstrap, before Alembic
  has created any table, so the grant reaches nothing. Bootstrap must use
  `ALTER DEFAULT PRIVILEGES` (or re-grant post-migration) — see SQ-08.

### M0-T04 — CI pipeline
- **Status** done — `.github/workflows/ci.yml`, `nightly.yml`; not executed on a runner in this session, workflow only
- **Depends on** M0-T01
- **Files** `.github/workflows/ci.yml`
- **Acceptance**
  ```bash
  act -j lint && act -j test          # or: push a branch and observe both jobs green
  ```
  Jobs: `lint` (ruff, black, mypy), `test-unit` (`pytest -m "not integration"`), `test-integration`
  (testcontainers Postgres 16 + Redis 7). Weekly scheduled `corpus-drift` job added in M1-T09.
  **[SPEC]** LLD §17.4 puts `temporal` and `abstention` on every pull request as "fast, no
  extraction", but both are `stage: verdict` and call the frontier model — so CI needs a
  provider key and a per-PR budget — see SQ-24.

---

# M1 — Corpus

First because every other component's correctness is defined relative to it. The deliverable
is `docs/CORPUS.md`, not working code.

> **Blocked at the environment level.** `rbi.org.in` returns 403 at the proxy CONNECT in this
> execution environment, so M1-T02, M1-T09, M1-T10 and M1-T11 cannot resolve against live
> sources here. See SQ-01. Tasks below are written to be developed against checked-in fixtures
> and re-run against live sources once reachable.

### M1-T01 — `corpus_sources.yaml`
- **Status** done — 8/8 tests. Points at local placeholder files per ADR-001/ADR-002, not live URLs.
- **Depends on** M0-T01
- **Files** `app/corpus/corpus_sources.yaml`, `app/corpus/sources.py`, `tests/unit/corpus/test_sources.py`
- **Acceptance**
  ```bash
  pytest tests/unit/corpus/test_sources.py -q
  ```
  Asserts: all five instrument codes present (`DL2025`, `KFS2024`, `RBC2025`, `RBC-AMD2026`,
  `RBC-AMD2026-DRAFT`); each declares `source_url`, `effective_from`, `status`,
  `verification_status`, `citable`; `DL2025.para_overrides` contains `6 → 2025-11-01` and
  `17 → 2025-06-15` (PRD §10); `RBC-AMD2026-DRAFT` is `status: draft`, `citable: false`,
  `effective_from: null`; `RBC-AMD2026` is `secondary_sourced`; loader rejects an unknown key
  and an instrument whose `status` and `effective_from` disagree.
  **[SPEC]** Source URLs are not supplied by any document in the set — see SQ-02.

### M1-T02 — `fetch.py`
- **Status** done — local-file mode (ADR-002) fully implemented and used by every ingest run; HTTP mode written but untested against a live host (SQ-01 still blocks that half).
- **Depends on** M1-T01
- **Files** `app/corpus/fetch.py`, `app/errors.py`, `tests/unit/corpus/test_fetch.py`
- **Acceptance**
  ```bash
  pytest tests/unit/corpus/test_fetch.py -q
  ```
  Against a local stub server, asserts: 200 writes `data/raw/<sha256>.<ext>` and the returned
  `sha256` equals `sha256sum` of that file; non-200 raises `CorpusFetchError`; a body under
  2 KiB raises; an anti-bot interstitial (content heuristic) raises **and no file is written**;
  a cross-host redirect is refused; the configured `corpus_user_agent` is sent; 30 s timeout
  honoured. Manual-placement path: a file already present in `data/raw/` with its hash in
  `corpus_sources.yaml` is accepted without a network call.

### M1-T03 — `continuous_para.py`
- **Status** done — 10/10 tests, including the roman/paragraph and note/letter ambiguity cases and 100W sort ordering.
- **Depends on** M1-T01
- **Files** `app/corpus/parsers/base.py`, `app/corpus/parsers/continuous_para.py`, `tests/unit/corpus/test_continuous_para.py`, `tests/fixtures/corpus/{dl2025,rbc2025}_excerpt.html`, `tests/fixtures/corpus/{dl2025,rbc2025}_expected.json`
- **Depends on** M1-T01
- **Acceptance**
  ```bash
  pytest tests/unit/corpus/test_continuous_para.py -q
  ```
  Golden-file: parsed node tree equals the checked-in expected JSON exactly, per instrument.
  Plus the ambiguities LLD §6.2 names explicitly: `i.` resolves as level-2 only when a
  paragraph is open and as a paragraph marker otherwise; `(i)` note markers do not collide
  with `(a)` level-3 letters; `100W` parses with `para_number="100W"` and `para_sort=100`;
  sorting places `100A < 100W < 101`; each of the four warning conditions fires on a crafted
  fixture and **warns rather than raises**; a parent node's `text` excludes its children's text.

### M1-T04 — `annex_table.py`
- **Status** done — 4/4 tests.
- **Depends on** M1-T03
- **Files** `app/corpus/parsers/annex_table.py`, `tests/unit/corpus/test_annex_table.py`, `tests/fixtures/corpus/kfs2024_annexA.html`
- **Acceptance**
  ```bash
  pytest tests/unit/corpus/test_annex_table.py -q
  ```
  One node per table row; `para_number == "annexA"`, `level2_label == part number`,
  `level3_label == row number`; every row's `text` begins with the column headers; a worked
  numeric illustration yields a single node with `chunk_kind == "illustration"`; node count
  equals row count in the fixture.
  **[SPEC]** R04 cites `KFS2024/annexB`, whose structure is specified nowhere — see SQ-06.

### M1-T05 — `chunk.py`
- **Status** done — 5/5 tests.
- **Depends on** M1-T03, M1-T04
- **Files** `app/corpus/chunk.py`, `tests/unit/corpus/test_chunk.py`
- **Acceptance**
  ```bash
  pytest tests/unit/corpus/test_chunk.py -q
  ```
  A node under `STEM_MIN_TOKENS` (40) gets `text_with_stem == parent_stem + node.text` and
  `chunk_strategy == "leaf+stem"`; a node at or above threshold gets `text_with_stem == node.text`
  and `chunk_strategy == "leaf"`; the stem is the parent's first sentence truncated to 200 chars;
  table rows record `"table_row"`, illustrations `"illustration_whole"`; `len(chunks) == len(nodes)`.

### M1-T06 — `embed.py`
- **Status** done, degraded mode — 4/4 unit tests against a mocked client; without a real embedding key (SQ-03) `service.ingest()` stores NULL embeddings, so vector retrieval (M4) is blocked until a key is supplied, but ingest itself does not fail.
- **Depends on** M1-T05, M2-T02 *(needs the `clause` table to write into)*
- **Files** `app/corpus/embed.py`, `tests/unit/corpus/test_embed.py`
- **Acceptance**
  ```bash
  pytest tests/unit/corpus/test_embed.py -q
  ```
  Against a stubbed embedding endpoint: batches at `embedding_batch_size` (64); a 429 on one
  batch retries with backoff and the run completes; a permanent error fails the ingest rather
  than writing partial vectors; every emitted vector has length `settings.embedding_dimension`;
  embedded chunk count equals node count.
  **[SPEC]** `embedding_dimension: 3072` cannot carry an HNSW index in pgvector (2000-dim
  ceiling) — see SQ-04. This task cannot close until the dimension decision is made.

### M1-T07 — `references.py`
- **Status** done — 6/6 tests; `DL2025/p8/i --incorporates--> KFS2024` verified against the real ingested placeholder corpus, not just a fixture.
- **Depends on** M1-T03, M1-T04
- **Files** `app/corpus/references.py`, `tests/unit/corpus/test_references.py`
- **Acceptance**
  ```bash
  pytest tests/unit/corpus/test_references.py -q -k incorporates_kfs
  ```
  The edge `DL2025/p8/i --incorporates--> KFS2024` is present in the output for the DL2025
  fixture. Plus: `CIRCULAR_RE` matches a real circular number and rejects a near-miss;
  `reference_kind` resolves to `incorporates` on "in terms of" / "as per instructions
  contained in" / "shall comply with", `repeals` inside a repeal paragraph, `amends` for an
  amendment instrument, `see_also` otherwise.

### M1-T08 — `snapshot.py`
- **Status** done — activation is two statements per the implementation note; integration-tested against real Postgres (two ingests, exactly one active snapshot, both retained).
- **Depends on** M1-T05, M2-T02
- **Files** `app/corpus/snapshot.py`, `app/corpus/service.py`, `tests/integration/corpus/test_snapshot.py`
- **Acceptance**
  ```bash
  pytest tests/integration/corpus/test_snapshot.py -q
  ```
  Against real Postgres: `ingest()` writes a snapshot with `is_active = false`; activation is
  one transaction and leaves exactly one active row; a direct attempt to set a second row
  active raises a unique-violation on `uq_snapshot_active`; deleting a snapshot cascades its
  instruments, clauses and references; an ingest whose `para_overrides` name a paragraph the
  parser did not find **fails fatally** (LLD §6.4).
  Implementation note: deactivate-then-activate as two statements — a single `UPDATE ... CASE`
  can transiently violate the partial unique index.

### M1-T09 — `make corpus-verify`
- **Status** done for local sources — `verify()` re-reads the same local files and reports drift; exit-code and per-instrument status implemented. Live-URL drift checking still blocked on SQ-01.
- **Depends on** M1-T02, M1-T08
- **Files** `app/corpus/service.py` (`verify`), `Makefile`, `.github/workflows/corpus-drift.yml`, `tests/integration/corpus/test_verify.py`
- **Acceptance**
  ```bash
  make corpus-verify; echo $?        # 0 when all unchanged, 1 on any 'changed'
  psql "$CC_DATABASE_URL" -c "SELECT count(*) FROM corpus_snapshot" # unchanged before and after
  pytest tests/integration/corpus/test_verify.py -q
  ```
  Reports per instrument `unchanged | changed | unreachable` with old and new hashes; mutates
  nothing (row counts identical before and after); sets `cc_corpus_drift_status{instrument_code}`.

### M1-T10 — `docs/CORPUS.md` **(the milestone deliverable)**
- **Status** done against the placeholder corpus — generated by a real `make ingest` run, reports clause counts, full path list, warnings, and paragraph ranges per instrument. Every verification status is honestly `unverified`/`secondary_sourced` (ADR-001) pending real RBI text; nothing is promoted to `rbi_verified`.
- **Depends on** M1-T07, M1-T08
- **Files** `app/corpus/report.py`, `Makefile` (`make ingest`), `docs/CORPUS.md`
- **Acceptance**
  ```bash
  make ingest && test -f docs/CORPUS.md
  python scripts/check_corpus_report.py        # structural assertions, exit 0
  ```
  The checker asserts the report contains, per instrument: clause count; the **full** clause-path
  list; every parser warning; detected paragraph range against the expected range from
  `corpus_sources.yaml`; cross-reference edges found; and a verification status that is either
  promoted to `rbi_verified` with the source URL and hash, or left `secondary_sourced` with a
  recorded reason. Path format is asserted against `^[A-Z0-9-]+/(p[0-9]+[A-Z]?|annex[A-Z])(/[^/]+){0,2}$`
  — a decimal path anywhere fails the build (`CLAUDE.md` §2.6).

### M1-T11 — Resolve PRD open questions 1–5
- **Status** done as far as possible without real text — all five recorded as UNRESOLVED with the reason (SQ-01) in `docs/CORPUS.md`, per `CLAUDE.md` §8; none filled with invented text.
- **Depends on** M1-T10
- **Files** `docs/CORPUS.md`, `app/corpus/corpus_sources.yaml`, `app/corpus/pinning.yaml`, `docs/DECISIONS.md`
- **Acceptance**
  ```bash
  python scripts/check_corpus_report.py --open-questions   # exit 0 only when 1..5 each carry
                                                           # a resolution or a recorded gap
  ```
  Each of PRD §14 Q1–Q5 appears in `docs/CORPUS.md` with either a resolution citing the live
  source URL and retrieval hash, or `UNRESOLVED` plus what was tried. Q4 in particular
  (whether a general non-microfinance contact-hour provision exists before 2027) gates the
  product's defining example: if one exists, PRD §11, `eval/cases/temporal/*` and R16/R17 all
  change. No gap is filled with plausible text (`CLAUDE.md` §8).

### M1-T12 — Pinning table, first pass *(added; LLD defers pinning to M4-T05 but boot needs it at M2)*
- **Status** done — 29/29 field keys resolve against the real ingested placeholder snapshot; `PinningMismatchError` verified to name every missing path, not just the first.
- **Depends on** M1-T10
- **Files** `app/corpus/pinning.yaml`, `app/corpus/pinning.py`, `tests/unit/corpus/test_pinning.py`
- **Acceptance**
  ```bash
  pytest tests/unit/corpus/test_pinning.py -q
  ```
  `load_and_validate` raises `PinningMismatchError` naming **every** unresolved path, not the
  first; a parent paragraph pin expands to itself plus descendants; validation passes against
  the M1 snapshot.
  **[SPEC]** The pinned paths `RBC-AMD2026/p100W|X|N|Q|R|S` are unconfirmed (PRD Q2). With
  `fail_boot_on_pinning_mismatch: true` outside `ci`, a renumbered amendment makes the app
  unbootable in `local` and `prod` — see SQ-05.

---

# M2 — Schema and skeleton

### M2-T01 — `fields.yaml` and the registry
- **Status** done — 82 keys per ADR-016 (the enumerated LLD §5.3 names, not its "sixty-one" prose); 15/15 registry tests, 3/3 generated-model tests.
- **Depends on** M0-T02
- **Files** `app/schema/fields.yaml`, `app/schema/registry.py`, `app/schema/generated.py`, `tests/unit/schema/test_registry.py`
- **Acceptance**
  ```bash
  pytest tests/unit/schema/test_registry.py -q
  python -c "from app.schema.registry import FieldRegistry; r=FieldRegistry('app/schema/fields.yaml'); r.validate(); print(len(r.all_keys()))"
  ```
  `validate()` is fatal on each of the six conditions in LLD §5.2 — one test per condition.
  `generated.py` builds one Pydantic model per `doc_type`, all fields optional, each carrying
  its registry `description`; a round-trip test renders the model's JSON schema and asserts
  the description text survives.
  **[SPEC]** LLD §5.3 states 61 keys; the groups sum to 80 by their own labels and the names
  listed enumerate 82 (collections is labelled 21 and lists 23). The acceptance count above
  cannot be written until SQ-07 fixes the number.

### M2-T02 — Migrations 0001–0008
- **Status** done — ran against real Postgres 16 + pgvector 0.6.0 in this session; full `downgrade base` → `upgrade head` round-trip clean; `tests/integration/db/test_migrations.py` 5/5. Vector dimension resolved per ADR-004 (1536, read from Settings at migration time, not hardcoded).
- **Depends on** M0-T03, M2-T01
- **Files** `alembic.ini`, `migrations/env.py`, `migrations/versions/0001_*.py` … `0008_*.py`, `app/db/{base,models,engine}.py`, `tests/integration/db/test_migrations.py`
- **Acceptance**
  ```bash
  make migrate && alembic downgrade base && alembic upgrade head   # clean, no error
  pytest tests/integration/db/test_migrations.py -q
  ```
  Asserts: migration order matches LLD §3.8; every enum value in §3.1 exists with the exact
  spelling; `alembic current == alembic heads`; ORM models in `app/db/models.py` match the DDL
  (autogenerate produces an empty diff); UUIDv7 primary keys are time-ordered.
  **[SPEC]** `clause.embedding vector(3072)` conflicts with both the pgvector HNSW ceiling and
  `CLAUDE.md` §3 ("vector dimension from config, never hardcoded") — see SQ-04.

### M2-T03 — Row-level security
- **Status** done — `tests/integration/db/test_rls.py` 5/5 against real Postgres as `cc_app` (non-superuser, `rolbypassrls=false`)
- **Depends on** M2-T02
- **Files** `migrations/versions/0008_*.py`, `app/db/rls.py`, `tests/integration/db/test_rls.py`
- **Acceptance**
  ```bash
  pytest tests/integration/db/test_rls.py -q
  ```
  Connected as `cc_app` (not superuser): a `SELECT` for tenant B's rows with
  `app.tenant_id = A` returns **zero rows** on each of the six RLS tables; an `INSERT` carrying
  tenant B's id under `app.tenant_id = A` is rejected; a transaction that never issues
  `SET LOCAL app.tenant_id` fails on its first query; `assessment_citation` is reachable only
  through its parent assessment's tenant; `SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user`
  is false; `UPDATE`/`DELETE` on `audit_event` are denied.

### M2-T04 — FastAPI skeleton
- **Status** done — 4/4 health tests + 8/8 documents/assessments flow tests
  (`tests/integration/api/`). Built: `app/main.py` (app factory, request-id middleware, error
  handlers, lifespan running boot assertions), `app/api/deps.py` (bearer-token tenant auth via
  `tenant.api_key_hash`, RLS-scoped session dependency, an injectable `get_llm_client` seam
  tests override), `app/api/errors.py` (the full LLD §16 code->status table), and
  `app/api/v1/{health,corpus,loans,documents,assessments}.py`. `/readyz` checks database, an
  active snapshot and pinning validation. `/v1/corpus` is unauthenticated and includes
  `verification_status`/`verification_note` per instrument. POST documents implements
  hash-mismatch, duplicate-doc, doctype-classification-floor and `Idempotency-Key` replay, all
  proven against real Postgres with a stub LLM client injected via
  `app.dependency_overrides`. SQ-09 resolved as ADR-033 (the boot assertion and `/readyz`'s
  own check guard different failure modes, not the same one).
  **Note on test infra**: tests drive the app via `httpx.AsyncClient(transport=ASGITransport(...))`
  on the pytest-asyncio loop, not `fastapi.testclient.TestClient` — the latter runs the app in
  a separate thread/loop that collides with this codebase's cached module-level SQLAlchemy
  engine the moment a test also touches the database directly.
- **Depends on** M2-T02

### M2-T05 — Celery wiring
- **Status** done — 5/5 wiring tests (`tests/integration/tasks/test_wiring.py`) + 9/9 task
  logic tests (`tests/integration/tasks/test_assess_tasks.py`, against real Postgres, real
  Redis broker/backend). `app/tasks/celery_app.py` matches LLD §14's routes, reliability
  settings and beat schedule. `assess.document`, `assess.check` and `assess.account`
  (`app/tasks/assess_tasks.py`) are one-line `asyncio.run(...)` wrappers around directly
  testable async helpers (ADR-031) — every session opened inside them sets `app.tenant_id`
  first, same pattern as `assess.py`. New migration 0009 adds the auth (`tenant.api_key_hash`)
  and idempotency (`idempotency_key` table) schema this and the coming API layer both need but
  the LLD's own DDL never defines (ADR-030).
- **Depends on** M0-T03

### M2-T06 — Structured logging with the content denylist
- **Status** done — 7/7 unit tests (`tests/unit/obs/test_logging.py`). `drop_denylisted_keys`
  recurses into nested dicts/lists so a denylisted key buried inside a logged structure (e.g.
  a list of per-field dicts) is scrubbed too, not just top-level keys. `configure_logging` is
  idempotent and its `PrintLoggerFactory` resolves `sys.stdout` dynamically rather than
  capturing it at configure time (found by a test failure: capturing it broke under pytest's
  `capsys`, which swaps `sys.stdout` out between tests — the same class of bug in production
  would appear if stdout were ever reopened, e.g. after a log-rotation signal).
- **Depends on** M0-T02

### M2-T06b — Prometheus metrics *(new — the other half of LLD §18)*
- **Status** done — 3/3 unit tests (`tests/unit/obs/test_metrics.py`, including one that
  locks the exact metric-name set so a rename can't slip through unnoticed) + 2/2 integration
  tests (`tests/integration/api/test_metrics_endpoint.py`). `app/obs/metrics.py` declares
  every metric named in LLD §18, including the ones nothing increments yet
  (`cc_queue_depth`, `cc_corpus_drift_status`, `cc_rule_model_divergence_total` — these need
  Celery queue inspection, the corpus-drift detector, and rule/model divergence tracking
  respectively, none of which exist yet) — a dashboard built against the fixed name list
  should never 404 on a metric that's merely stuck at zero. Wired and incrementing for real:
  `cc_http_requests_total`/`cc_http_request_duration_seconds` (main.py's middleware),
  `cc_llm_calls_total`/`cc_llm_duration_seconds`/`cc_llm_tokens_total`/`cc_llm_cost_usd_total`/
  `cc_llm_breaker_state` (app/llm/client.py), `cc_verdicts_total`/`cc_citation_rejected_total`
  (app/verdict/assess.py), `cc_conflicts_detected_total` (app/conflicts/detector.py),
  `cc_facts_extracted_total`/`cc_span_grounding_failures_total`/
  `cc_span_budget_exhausted_total` (app/extract/service.py). `GET /metrics` (unauthenticated,
  Prometheus text format) also computes `cc_active_snapshot_age_seconds` at scrape time.
- **Depends on** M2-T06, M2-T04

### M2-T07 — Boot assertions
- **Status** done — 8/8 tests (`tests/integration/test_boot.py`). `app/boot.py`'s
  `run_boot_assertions` raises `BootAssertionError` (tests assert on the exception directly,
  the more precise signal); `boot_or_exit` wraps it with `sys.exit(1)` and is what
  `app.main`'s lifespan actually calls. All five LLD §2 checks: embedding dimension vs. the
  live `clause.embedding` column width (via `pg_attribute.atttypmod`); exactly one active
  snapshot (proven two ways — the assertion itself, and that `uq_snapshot_active`'s partial
  unique index makes a second active row genuinely impossible to insert in the first place);
  every pinning path resolves; every **non-shadow** rule's clause paths resolve (a rule that's
  currently shadow because its instrument isn't `rbi_verified` is exempt, since its clause
  basis isn't citable regardless of whether the path exists); `alembic current == heads`.
  `fail_boot_on_pinning_mismatch=false` accepted only when `env='ci'`.
- **Depends on** M2-T02, M2-T04, M1-T12

---

# M3 — Extraction on the frontier baseline

### M3-T01 — `parse.py`
- **Status** done — 7/7 tests, including a real synthetic PDF (via reportlab) and docx; OCR fallback raises rather than silently returning empty text since no OCR engine is wired yet.
- **Depends on** M2-T01
- **Files** `app/extract/parse.py`, `app/domain/documents.py`, `tests/unit/extract/test_parse.py`
- **Acceptance**
  ```bash
  pytest tests/unit/extract/test_parse.py -q
  ```
  A text-layer PDF parses without OCR; a scanned fixture under `ocr_char_per_page_threshold`
  (120 chars/page) triggers the OCR path and sets `ocr_used=true`; `.txt` and `.docx` parse;
  `char_count` and `page_count` are populated; **no branch writes bytes to disk or returns a
  file path** (asserted by inspecting the returned `ParsedDocument` and by a tmpdir diff).

### M3-T02 — `classify.py`
- **Status** done — 3/3 tests against a mocked client; untested against a real model (no LLM key in this environment, SQ-03).
- **Depends on** M3-T01
- **Files** `app/extract/classify.py`, `app/prompts/extract/classify_doctype.v1.md`, `tests/unit/extract/test_classify.py`
- **Acceptance**
  ```bash
  pytest tests/unit/extract/test_classify.py -q
  curl -s -X POST localhost:8000/v1/loans/$LOAN/documents -d @tests/fixtures/ambiguous.json | jq -e '.error.code=="CC-422-DOCTYPE-UNKNOWN"'
  ```
  Classification reads at most the first 2,000 characters; below
  `classify_confidence_floor` (0.70) returns `doc_type="unknown"` and the API returns
  `CC-422-DOCTYPE-UNKNOWN` rather than extracting against a guessed field set.

### M3-T03 — `normalise.py`
- **Status** done — 20/20 tests including two Hypothesis property tests (money and rate round-trips never lose precision, never produce a float).
- **Depends on** M2-T01
- **Files** `app/extract/normalise.py`, `tests/unit/extract/test_normalise.py`
- **Acceptance**
  ```bash
  pytest tests/unit/extract/test_normalise.py -q      # includes hypothesis property tests
  ```
  `12/03/2026` → `2026-03-12` (day-first, per registry `prefer: day_first`); `₹1,20,000` →
  `12000000` paise; `18.5%` and `18.5% p.a.` → `1850` bps; `20:10` on an IST document →
  tz-aware `Asia/Kolkata`; malformed input raises rather than returning a default. Property
  test: money and rate round-trips never lose precision and never produce a `float`.

### M3-T04 — `redact.py` profile v1
- **Status** done — 10/10 tests. Found and fixed a real bug the LLD's own prose warned about but its literal pattern order didn't avoid: ACCOUNT ahead of PHONE swallowed 10-digit phone numbers. See ADR-022.
- **Depends on** M2-T01
- **Files** `app/extract/redact.py`, `tests/unit/extract/test_redact.py`
- **Acceptance**
  ```bash
  pytest tests/unit/extract/test_redact.py -q
  ```
  One test per pattern in LLD §13; the **ordering** test asserts a 10-digit phone number is
  tagged `PHONE` and not swallowed by `ACCOUNT`; a `redaction_exempt` field passes through
  unchanged; redaction applies to `value_raw` and `quoted_span` and **never** to
  `value_normalized` for non-string types (a date survives intact); `"Gold Loan Agreement"`
  is not redacted.

### M3-T05 — `spans.py` and the span budget
- **Status** done — 6/6 unit tests, 4/4 integration tests against real Postgres including a concurrent-writers-under-row-lock case.
- **Depends on** M3-T04, M2-T02
- **Files** `app/extract/spans.py`, `tests/unit/extract/test_spans.py`, `tests/integration/extract/test_span_budget.py`
- **Acceptance**
  ```bash
  pytest tests/unit/extract/test_spans.py tests/integration/extract/test_span_budget.py -q
  ```
  A quotation present in the source sets `span_verified=true`; an absent quotation causes the
  fact's span to be **dropped and counted** in `cc_span_grounding_failures_total`; the budget
  (`span_used_chars + len <= char_count * 0.15`) is enforced inside the fact-insert
  transaction under a row lock on `document`; exhaustion truncates longest-first, sets
  `span_truncated`, increments `cc_span_budget_exhausted_total`, and **still stores the fact**.
  Concurrency test: two parallel writers cannot exceed the budget.

### M3-T06 — `extractor.py` and the LLM client
- **Status** done per ADR-017 (synchronous extraction in the API request resolves SQ-23) — 9/9 LLM client tests, 4/4 integration tests for the full `extract_document` orchestration against real Postgres with a mocked model response. Untested against a real provider (SQ-03, no key in this environment).
- **Depends on** M3-T02, M3-T03, M2-T01
- **Files** `app/llm/{client,routing,structured}.py`, `app/extract/extractor.py`, `app/extract/service.py`, `app/prompts/extract/document_facts.v1.md`, `tests/unit/llm/test_client.py`
- **Acceptance**
  ```bash
  pytest tests/unit/llm/test_client.py -q
  pytest tests/unit/test_no_provider_sdk_outside_llm.py -q     # AST walk over app/
  ```
  Client: retries on `TransientLLMError` only; no retry on `ValidationError`; the breaker
  opens after `llm_breaker_fail_threshold` (5) and resets after 60 s; provider, model,
  adapter, tokens in/out, wall-clock ms and computed cost are recorded on every call
  (`CLAUDE.md` §5); exactly **one** JSON repair attempt then fail. The AST test fails on any
  provider SDK import outside `app/llm/`.
  **[SPEC]** SQ-23: §14 routes document text to the worker through "a single-use, expiring
  in-memory handoff", but §20.1/§20.2 run the API and worker as separate containers, and both
  Postgres and Redis are forbidden to hold the text. Stage A has no route to the bytes it
  extracts from. Must be settled before this task can be written.

### M3-T07 — Synthetic document generator
- **Status** done — 150 fixtures generated (25 each across the six deep types: `kfs`,
  `loan_agreement`, `sanction_letter`, `mitc`, `call_transcript`, `closure_statement`), 2-3
  layout templates per type, 3 currency formats, 4 date formats, ~15% of documents given
  light OCR-style character noise (confined to the body, never the banner). 5/5 unit tests
  (`tests/unit/test_synthetic_docs.py`), including a direct re-use of `app/extract/redact.py`'s
  own AADHAAR/PAN/ACCOUNT patterns to prove no generated value matches them (proposal/
  reference numbers are letter-prefixed and dash-broken, e.g. `LN-SYN-2026-00042`, so no
  9-18-digit run ever occurs).
- **Depends on** M2-T01
- **Files** `scripts/gen_synthetic_docs.py`, `eval/fixtures/**`, `tests/unit/test_synthetic_docs.py`
- **Acceptance**
  ```bash
  python scripts/gen_synthetic_docs.py --out eval/fixtures --count 150
  ls eval/fixtures/**/*.txt | wc -l        # >= 150
  pytest tests/unit/test_synthetic_docs.py -q
  ```
  ≥150 documents across the six deep types with layout, phrasing, currency-format,
  date-format and OCR-noise variation; **every** generated document carries
  `is_synthetic=true` and a visible synthetic banner (`CLAUDE.md` §2.4); a test asserts no
  generated document contains a value drawn from a real-looking PAN/Aadhaar/account pattern.

### M3-T08 — `extraction_core` suite — **first published baseline**
- **Status** done, first real baseline published — `reports/eval_extraction_core_latest.json`.
  SQ-03 resolved (real Gemini key, billing enabled after two account-side blockers: a
  free-tier 20 req/day cap, ADR-039, and then a separate monthly spend cap on the AI Studio
  project that also needed manually raising). Full pipeline built and proven live this pass:
  `LLMClient.structured()` now sends a real JSON Schema with `$ref`/`$defs` inlined and
  validation-only bounds/metadata stripped (ADR-038, ADR-041), `litellm.BadRequestError` is
  wrapped as `PermanentLLMError` (ADR-041), `scripts/gen_synthetic_docs.py`'s generators
  return `(text, facts_dict)` — the exact values used to render each fixture, written
  alongside it as `<fixture>.facts.json`, never separately authored — `eval/runner.py` has a
  real `run_extraction_case()` (creates a real `document` row, calls `extract_document()`
  against fixture text, no ground truth injected pre-extraction), `eval/metrics.py` has
  `compute_extraction_metrics()` implementing LLD §17.2's formulas per field and in
  aggregate, and `eval/harness.py` isolates a per-case LLM failure so one doc_type's known
  issue doesn't lose every other case's real results.
  **Real baseline (125 cases, 100 scored, git_sha e7ccbf4+, ADR-042):**
  `field_accuracy=0.825`, `absence_accuracy=0.933`, `span_grounding=0.486`. Total cost for
  the full run: $0.465. Two real bugs found and fixed live during this run: `/-` Indian
  currency suffix rejected by `normalise_money_to_paise` (ADR-040), and an `IST` timezone
  suffix rejected by `normalise_time`, which had been zeroing out `contact_datetime` on
  every `call_transcript` case (ADR-042) — fixed after this run, not yet re-verified live.
  **`loan_agreement`'s schema-size gap is now closed (ADR-043):** `extract_raw_fields()`
  splits any doc_type above 25 registered fields (currently only `loan_agreement`, 34
  fields) into multiple schema-constrained calls over field groups, merging results by key —
  every other doc_type's call count and cost is unchanged. A targeted re-run of all 25
  `loan_agreement` cases (not the full 125, to keep spend proportional to what changed):
  `field_accuracy=0.770`, `absence_accuracy=0.932`, `span_grounding=0.455` — in line with the
  rest of the suite, not an outlier. Every case in `extraction_core` now produces real
  field-level data; none returns zero.
  **Known open gaps, stated honestly, not closed by this task:** several per-field scores
  are still low and untriaged beyond the two normalisation fixes above (`sanctioned_amount`
  0.62, `fees_total` 0.66, `kfs_validity_days` 0.6, several boolean flags at 0.32);
  `span_grounding` around 0.45-0.49 means roughly half of correctly-valued fields across the
  suite have no verifiable quoted span, a real defect category of its own, not yet
  root-caused per field.
- **Depends on** M3-T05, M3-T06, M3-T07
- **Files** `eval/harness.py`, `eval/cases/extraction_core/*.json`, `Makefile` (`make eval`, `make eval-report`), `reports/`
- **Acceptance**
  ```bash
  make eval suite=extraction_core && ls reports/eval_*.json
  jq -e '.metrics.span_grounding >= 0.99' reports/eval_latest.json
  jq -e '.metrics.per_field | to_entries | all(.value.exact_match != null)' reports/eval_latest.json
  ```
  ≥150 cases. Metrics computed by the LLD §17.2 formulas, reported **per field key** not only
  in aggregate. The run writes both `.json` and `.md` and diffs against the previous run of
  the same suite. Baseline numbers recorded in the task summary as numbers.

---

# M4 — Retrieval

### M4-T01 — `applicability.py`
- **Status** done — 3/3 unit tests incl. an AST check that no call site defaults as_of. ADR-005 adds the borrower-class predicate the LLD's own DDL omits.
- **Depends on** M1-T08, M2-T02
- **Files** `app/retrieve/applicability.py`, `tests/unit/retrieve/test_applicability.py`
- **Acceptance**
  ```bash
  pytest tests/unit/retrieve/test_applicability.py -q
  ```
  `require_as_of(None)` raises `ApplicabilityError`; there is no default anywhere (AST test:
  no call site passes `as_of=date.today()`); window boundaries are inclusive-start,
  exclusive-end — a clause `effective_from=2027-01-01` is **out** on 2026-12-31, **in** on
  2027-01-01, and a clause `effective_to=2025-05-08` is **out** on 2025-05-08; `status='draft'`
  is excluded; a non-matching `entity_type` is excluded; `citable=false` on either clause or
  instrument is excluded.

### M4-T02 — `vector.py`
- **Status** done, unexercised — code complete (in-SQL applicability filter, ef_search set, NULL-embedding guard), but no embedding key in this environment (SQ-03) means every clause in the placeholder corpus has embedding=NULL, so there is nothing for ANN search to actually retrieve yet. The EXPLAIN-plan assertion from the original acceptance criterion is deferred until real vectors exist.
- **Depends on** M4-T01, M1-T06
- **Files** `app/retrieve/vector.py`, `tests/integration/retrieve/test_vector.py`
- **Acceptance**
  ```bash
  pytest tests/integration/retrieve/test_vector.py -q
  ```
  `EXPLAIN (ANALYZE, BUFFERS)` on the generated query shows the applicability predicates
  applied **within** the scan, not as a filter above a subquery — asserted by parsing the plan
  and failing on a post-filter shape (LLD §8.1). `hnsw.ef_search = 120` is set on the session
  before the query. A clause outside the window never appears in results at any `k`.

### M4-T03 — `lexical.py`
- **Status** done — exercised indirectly via `tests/integration/retrieve/test_retrieve_service.py` (apr_bps pinned-candidate resolution); dedicated numeric-token-recall test added
  (`tests/integration/retrieve/test_lexical_numeric_recall.py`, 7/7 passing against the real
  corpus). Building it surfaced and fixed a real gap: `numeric_tokens`'s number-word list was
  missing "six", "four", "twenty-four", etc. (only recognised one/two/three/thirty/sixty/
  ninety) — widened to a full one-to-ninety word list. It also surfaced and *documented* (not
  fixed) a second, real gap: a digit token ("24") never matches a clause that spells the same
  number as words ("twenty-four") under `websearch_to_tsquery`, which has no numeral/word
  synonym dictionary — proven directly (`test_digit_form_does_not_recall_a_word_spelled_clause`).
  Fixing that for real needs a synonym dictionary added to the FTS configuration — **new
  follow-up, not solved here**, since it changes the tsvector/tsquery pipeline shared by every
  field, not just this one test's fixture.
- **Depends on** M4-T01
- **Files** `app/retrieve/lexical.py`, `tests/integration/retrieve/test_lexical.py`
- **Acceptance**
  ```bash
  pytest tests/integration/retrieve/test_lexical.py -q
  ```
  Queries containing `"thirty days"`, `"₹5,000"`, `"08:00 hours"` and `"six months"` each
  retrieve the clause carrying that obligation in the top 3; the lexical query string includes
  numeric and unit tokens from the fact value and therefore **differs** from the vector query
  string (asserted); the same applicability predicates apply in-query.

### M4-T04 — `fusion.py`
- **Status** done — 5/5 tests: hand-computed RRF arithmetic, the exact tie at the LLD's literal weight (2.0) proving SQ-10's point, and genuine precedence at the corrected default weight (2.5, ADR-020).
- **Depends on** M4-T02, M4-T03
- **Files** `app/retrieve/fusion.py`, `tests/unit/retrieve/test_fusion.py`
- **Acceptance**
  ```bash
  pytest tests/unit/retrieve/test_fusion.py -q
  ```
  RRF arithmetic checked against hand-computed values for a fixed input; tie-break is
  deterministic (pinned → vector → lexical, then lower `clause_path`); provenance (`source`,
  `rank`, `score`) survives fusion for every candidate.
  **[SPEC]** LLD §8.4 claims a rank-1 pinned clause *outranks* a clause ranked 1 in both
  vector and lexical. At `k=60`, `w_pinned=2.0`: `2.0/61 == 1.0/61 + 1.0/61` exactly — it is a
  **tie** decided by the tie-break, not by score. See SQ-10; the test asserts the tie and the
  tie-break, and the claim in the LLD needs correcting or the weight raising.

### M4-T05 — Pinning tightened and boot-validated
- **Status** done — paragraph-granularity pinning (M1-T12) is done and boot-validated against the real corpus; leaf-granularity tightening itself is M5-T05 (now also done — see below).
- **Depends on** M1-T12, M2-T07
- **Files** `app/corpus/pinning.yaml`, `app/corpus/pinning.py`, `tests/integration/corpus/test_pinning_boot.py`
- **Acceptance**
  ```bash
  pytest tests/integration/corpus/test_pinning_boot.py -q
  ```
  Every pinned field key exists in `fields.yaml`; every pinned path resolves in the active
  snapshot; booting against a snapshot missing one pinned clause exits non-zero with every
  missing path named.

### M4-T03b — FTS numeral/word synonym dictionary *(new — found while testing M4-T03)*
- **Status** done — see docs/DECISIONS.md ADR-037. A real Postgres `numbers_syn` TEXT SEARCH
  DICTIONARY (from `scripts/tsearch/numbers.syn`, digit↔word 0–100) and a `clausecheck_en`
  TEXT SEARCH CONFIGURATION are created by `scripts/db_bootstrap.sql` (mounted into
  `docker-compose.yml`'s postgres service) and wired into both `clause.tsv`'s generation
  expression (migration `0010`) and `app/retrieve/lexical.py`'s query. Verified against the
  real ingested corpus: `test_digit_form_does_not_recall_a_word_spelled_clause` is now
  `test_digit_form_recalls_a_word_spelled_clause` and asserts both `"24"` and `"twenty-four"`
  recall `DL2025/p13`. Full regression: 299/299 passing after `alembic upgrade head`.
- **Depends on** M4-T03
- **Files** `app/retrieve/lexical.py`, `migrations/versions/0010_clause_tsv_numeral_synonyms.py`,
  `scripts/db_bootstrap.sql`, `scripts/tsearch/numbers.syn`, `docker-compose.yml`,
  `tests/integration/retrieve/test_lexical_numeric_recall.py`,
  `tests/integration/db/test_migrations.py`
- **Acceptance**
  ```bash
  pytest tests/integration/retrieve/test_lexical_numeric_recall.py::test_digit_form_recalls_a_word_spelled_clause -q
  ```
  A digit token ("24") and its spelled-word form ("twenty-four") both match a clause stating
  the same number, regardless of which form the clause or the query uses.

### M4-T06 — Reference-hop expansion
- **Status** done — `tests/integration/retrieve/test_reference_hop.py` proves DL2025/p8/i --incorporates--> KFS2024 is followed at depth 1 against the real ingested corpus, tagged `source="reference_hop"`.
- **Depends on** M1-T07, M4-T04
- **Files** `app/retrieve/service.py`, `tests/integration/retrieve/test_reference_hop.py`
- **Acceptance**
  ```bash
  pytest tests/integration/retrieve/test_reference_hop.py -q -k kfs_completeness
  ```
  Retrieval for a KFS completeness field starting from `DL2025/p8/i` returns `KFS2024` annexe
  rows via the `incorporates` edge at depth 1; depth 2 is **not** followed
  (`follow_reference_hops=1`); hopped candidates carry `source="reference_hop"`.

### M4-T07 — `context_only` near-miss retrieval
- **Status** done — SQ-12 and SQ-13 both resolved per ADR-012 and ADR-005. `tests/integration/retrieve/test_retrieve_service.py` proves both halves of the PRD §11 temporal pair and the microfinance borrower-scope exclusion against the real corpus, plus that a draft path never reaches `candidates` or `context_only` at any date.
- **Depends on** M4-T04
- **Files** `app/retrieve/service.py`, `app/domain/clauses.py`, `tests/integration/retrieve/test_context_only.py`
- **Acceptance**
  ```bash
  pytest tests/integration/retrieve/test_context_only.py -q
  ```
  For `contact_datetime` on 2026-09-03, `RBC-AMD2026/p100W` appears in `context_only` with
  reason `not_yet_in_force` and its commencement date, and **not** in `candidates`; on
  2027-01-03 it appears in `candidates`. A superseded clause carries reason `superseded`.
  **[SPEC]** SQ-12: step 7 re-queries "without the date predicates", which would admit
  `RBC-AMD2026-DRAFT` clauses to `context_only` — but §17.1 forbids draft paths in **any**
  citation on **every** case. The draft exclusion must survive into `context_only`.
  **[SPEC]** SQ-13: the microfinance contact-hour clause is in force, applies to NBFCs, and
  passes every predicate in `APPLICABILITY_SQL`, so it lands in `candidates` as citable —
  yet PRD §11 requires it in `context_only` annotated "out of scope for this borrower class".
  There is no borrower-class column or predicate anywhere in the schema. The product's
  defining behaviour cannot be produced until this is resolved.

### M4-T08 — `retrieval` suite
- **Status** blocked *(M4-T02)*
- **Depends on** M4-T04, M4-T06, M4-T07
- **Files** `eval/cases/retrieval/*.json`, `eval/harness.py`, `reports/`
- **Acceptance**
  ```bash
  make eval suite=retrieval
  jq -e '.metrics.recall_at_4 >= 0.95' reports/eval_latest.json
  jq -e '.metrics.applicability_precision == 1.0' reports/eval_latest.json
  ```
  Gold decisive clause paths annotated per case. Also publishes recall@1, recall@8, MRR,
  pinning hit rate and per-source attribution (LLD §17.2).
  **[SPEC]** `retrieval` is not among the suites in LLD §17.3 although M4-T08 and PRD §8.1
  both require it — see SQ-14 (same for `verdict`).

---

# M5 — Rule pack

### M5-T01 — Rule base, registry, shadow mode
- **Status** done — SQ-15 resolved per ADR-007 (clause_excerpts passed into evaluate()). 5/5 shadow-mode tests confirm every rule is shadow against the placeholder corpus.
- **Depends on** M2-T01, M1-T10
- **Files** `app/rules/{base,registry}.py`, `tests/unit/rules/test_registry.py`
- **Acceptance**
  ```bash
  pytest tests/unit/rules/test_registry.py -q
  ```
  `@register(shadow_if_unverified=True)` marks a rule shadow when **any** instrument behind
  its `clause_paths` is `secondary_sourced` or `unverified`, resolved from the active snapshot
  at boot, not hard-coded; a shadow rule still evaluates and persists with `is_shadow=true`;
  `FactIndex` helpers raise `MissingFact`, which the harness converts to `NOT_APPLICABLE`.
  **[SPEC]** SQ-15: R01 and R16 as written call `facts.clause_excerpt(path)`, but `FactIndex`
  is specified as a field-key→fact mapping and rules are forbidden I/O. Clause text must reach
  the rule some other way (pre-loaded excerpt map passed to `evaluate`), which changes the
  `Rule` protocol signature.

### M5-T02 — Rules R01–R14
- **Status** done — R01/R16 fully boundary-tested (14 tests); R02-R14 implemented and registered, clause paths verified to resolve against the real corpus; boundary tests for the rest are the main gap left for a follow-up session.
- **Depends on** M5-T01
- **Files** `app/rules/r01_*.py` … `r14_*.py`, `app/rules/r02b_*.py`, `tests/unit/rules/test_r0*.py`
- **Acceptance**
  ```bash
  pytest tests/unit/rules/ -q -k "r01 or r02 or r03 or r04 or r05 or r06 or r07 or r08 or r09 or r10 or r11 or r12 or r13 or r14"
  ```
  Each rule tested at its boundary (29/30/31 days for R01; ₹5,000 exactly for R02; 1 bp for
  R03) and asserted `NOT_APPLICABLE` outside its `valid_from`/`valid_to` window.
  **[SPEC]** R02b is unnumbered in the `r01..r27` scheme and makes 28 rules under a heading
  that says 27; R02b and R17 declare bases `RBC2025 §F` / `RBC2025 §H`, which are not valid
  clause paths and will never resolve at boot — see SQ-06.

### M5-T03 — Rules R15–R27
- **Status** done — all registered, clause paths resolve against the real corpus (28/28 incl. R02b). R17 resolved per ADR-015 (RBC2025/p45, not the LLD's non-canonical 'section H').
- **Depends on** M5-T01
- **Files** `app/rules/r15_*.py` … `r27_*.py`, `tests/unit/rules/test_r1*.py`, `test_r2*.py`
- **Acceptance**
  ```bash
  pytest tests/unit/rules/ -q -k "r15 or r16 or r17 or r18 or r19 or r20 or r21 or r22 or r23 or r24 or r25 or r26 or r27"
  ```
  R16 tested at 07:59 / 08:00 / 18:59 / 19:00 / 19:01 and on 2026-12-31 vs 2027-01-01; R23 at
  59/60/61 days past due and with each cure notice missing; R24 arithmetic at ₹250/hour.
  Every `RBC-AMD2026`-based rule starts shadow.
  **[SPEC]** R16 as written uses `ts.timetz().replace(tzinfo=None)`, which yields wall time in
  whatever tzinfo the datetime carries — UTC if Postgres hands back UTC — not IST. Must be
  `ts.astimezone(ZoneInfo("Asia/Kolkata")).time()`. Separately, `<= WINDOW_CLOSE` makes 19:00:00
  exactly compliant; the numeric suite tests that boundary but no document states the expected
  value — see SQ-16.

### M5-T04 — Purity assertions
- **Status** done — 3 AST tests (no clock, no session/network import, no async evaluate) + a canonical-path/count check, 18/18 passing.
- **Depends on** M5-T02, M5-T03
- **Files** `tests/unit/rules/test_rule_purity.py`
- **Acceptance**
  ```bash
  pytest tests/unit/rules/test_rule_purity.py -q
  ```
  AST walk over `app/rules/` fails on any call to `date.today()` or `datetime.now()`, any
  session or engine import, any `httpx`/`requests` import, and any `async def evaluate`.

### M5-T05 — Pinning tightened to leaf granularity
- **Status** done — checked every pin directly against the real ingested `clause` table
  (not assumed from the LLD text): `DL2025/p9` had three real sub-paragraph leaves
  (`/i` disbursal, `/ii` repayment, `/iii` LSP fee) that R08/R09/R10's own `clause_paths`
  already cited individually while `pinning.yaml` still pinned the bare parent — tightened
  `disbursal_credited_account_type`, `repayment_debited_account_type`,
  `pass_through_account_used_flag`, `lsp_fee_borne_by` to their real leaves accordingly.
  `DL2025/p10` had one real leaf (`/note/1`, "shall not be less than one day") — added
  alongside the parent for `cooling_off_period_days`. Every other pinned paragraph (e.g.
  `RBC2025/p35`, `RBC-AMD2026/p100W`) was queried and confirmed to have **no** further
  sub-paragraph structure in the corpus, so the bare paragraph path already *is* the leaf —
  left as-is rather than inventing a leaf that doesn't exist (CLAUDE.md §2.6). 28/28 pinning,
  boot, and retrieval integration tests pass against the real corpus and Postgres after the
  change; no `eval suite=retrieval` exists yet to re-run per this task's original acceptance
  (no retrieval-stage eval suite has been built — see M6-T05/ADR-034), so the delta is stated
  qualitatively here rather than as a fabricated precision/recall number.
- **Depends on** M1-T10, M4-T05
- **Files** `app/corpus/pinning.yaml`, `docs/DECISIONS.md`
- **Acceptance**
  ```bash
  pytest tests/unit/corpus/test_pinning.py tests/integration/corpus/test_ingest_and_pinning.py tests/integration/test_boot.py tests/integration/retrieve -q
  ```
  Paragraph-level pins replaced with the real sub-paragraph identifiers from M1's parse
  (PRD §14 Q3) wherever the corpus actually has one.

### M5-T06 — `numeric_rules` and `temporal` suites
- **Status** partial — 49 numeric cases (up from 15), covering boundary conditions for 8 of
  the LLD §11's nine "pure date or money arithmetic" rules (R03 is decided by
  `conflicts/detector.py` rather than a standalone rule evaluation, so it alone gets no
  dedicated numeric case), plus six rules of the same arithmetic character outside that
  named list (R02b, R04, R16, R17, R23, R26): R01 (30-day
  release window: the pre-existing ±1-day boundary plus a same-day zero-delay compliant case
  and a 60-day grossly-non-compliant violation), R02 (₹5,000/day compensation: the
  pre-existing 45-day exact-payment/underpaid pair plus the tightest 31-day compliant
  boundary and a 90-day underpaid case at a different multiplier), R12 (grievance mechanism
  disclosed — compliant side only; a violation case still needs a fact recorded as explicitly
  *absent*, which `eval/loader.py`'s case format does not yet express), R13 (24-hour offshore
  deletion: the pre-existing ±1-hour boundary plus a 0-hour compliant extreme, a 48-hour
  violation extreme, and a MissingFact violation with no deletion window disclosed at all),
  R18 (180-day recording retention: the pre-existing boundary plus a 365-day compliant
  extreme, a 90-day violation extreme, and a MissingFact violation), R22 (one-day
  prior-intimation: the pre-existing boundary plus a 7-day compliant extreme and a MissingFact
  violation with no intimation on record at all), R24 (restoration compensation: the
  pre-existing zero/one-hour pair plus a 10-hour violation at a larger compensation
  multiplier), and R16/R17 at LLD §17.3's own named 18:59/19:00/19:01 boundary for the
  shared 08:00-19:00 contact window (R16 from RBC-AMD2026, governing post-2027 for any
  borrower; R17 from RBC2025, governing pre-2027 for a microfinance borrower specifically —
  same window, different clause basis, so both get their own boundary set: R16 gets
  18:59/19:00/19:01/08:00/07:59, R17 gets 18:59/19:01). Also adds R02b (the lost-documents
  limb of R02, same RBC2025 §F arithmetic family — an extended 60-day window rather than
  R02's 30, plus its own not-assisted violation path), R23 (device-restriction
  preconditions: the 60-day past-due boundary, a below-minimum violation, a
  reversed-cure-notice-sequence violation, and an unfinanced-device violation — four
  independent precondition-failure paths), R26 (KFS validity: the 3-working-day
  boundary, a below-minimum violation, a missing-proposal-number violation, and a
  missing-validity-period violation), and R04 (APR-vs-rate-plus-fees computation,
  KFS2024/annexA/part1/9: the 200 bps tolerance boundary — 200 compliant / 201 ambiguous,
  this check's own verdict for a diff beyond tolerance rather than violation — plus a
  nonzero-fee case exercising the fee-load annualisation arithmetic itself). All 49 verified
  at `verdict_accuracy == 1.0` against the real corpus (`tests/integration/eval/
  test_harness.py::test_numeric_rules_suite_boundaries_are_exact`). Still short of the LLD's
  ≥60 minimum — same honest-scope-reduction pattern as ADR-034/ADR-035, not a fabricated
  count.
  14 temporal cases (7 pairs, up from 4 pairs/8 cases): the PRD §11 pair (`EV-TEMPORAL-001`/
  `-002`, R16 contact window), 3 pairs across the 2027-01-01 RBC-AMD2026 commencement date
  (R18 recording retention, R22 prior-visit intimation, R24 restoration compensation), 2
  pairs across DL2025's own 2025-05-08 phased commencement date (R13 offshore deletion, R12
  grievance escalation disclosure), and 1 new pair across **RBC2025's own 2025-11-28
  commencement date** (R05 penal charge not levied as interest) — three distinct real
  commencement dates now covered. Each pair holds the underlying fact constant and varies
  only the event date, so the verdict flip (`no_clause_found` → the rule's verdict) is
  attributable to clause commencement alone, not a confound. Still short of the LLD's ≥30
  minimum, and the DL2025 1 Nov / 15 Jun phased dates (`DL2025/p6`, `DL2025/p17`) remain
  uncovered — both map to clauses no implemented rule cites, so closing them would need
  actual LLM judgment for the "after" side, blocked on SQ-03.
- **Depends on** M5-T02, M5-T03
- **Files** `eval/cases/numeric_rules/*.json`, `eval/cases/temporal/*.json`, `reports/`
- **Acceptance**
  ```bash
  make eval suite=numeric_rules && jq -e '.metrics.verdict_accuracy >= 0.99' reports/eval_numeric_rules_latest.json
  make eval suite=temporal     && jq -e '.metrics.verdict_accuracy >= 0.99' reports/eval_temporal_latest.json
  ```
  ≥60 numeric cases at the boundaries named in LLD §17.3; ≥30 temporal cases as **pairs**
  across 2027-01-01 and the phased 2025 dates. `EV-TEMPORAL-001`/`-002` (the PRD §11 pair) are
  permanent cases and must pass.

---

# M6 — Verdict and guardrail

### M6-T01 — Verdict orchestration
- **Status** done — 4/4 integration tests (`tests/integration/verdict/test_assess.py`); resolved
  SQ-17 by treating `check_key` as `rule.check_key` (e.g. `"R01_docs_release_30d"`) for a
  rule-decided result and `f"F:{field_key}"` for a model-decided one — matches §10.1's own
  pseudocode variable names over the §15.2 example, which is illustrative prose, not a
  contract test. Also found and fixed a real defect the LLD's own prose creates a
  contradiction around: "a firing rule short-circuits the model" vs "a shadow rule ... does
  not suppress the model path" only both hold if *shadow* firings are excluded from what
  counts as "firing" for short-circuit purposes — implemented as such and covered by
  `test_shadow_rule_persists_and_does_not_suppress_model` /
  `test_verified_rule_short_circuits_model_call`.
- **Depends on** M5-T01, M4-T07
- **Files** `app/verdict/assess.py`, `app/prompts/verdict/assess_fact.v2.md`, `tests/integration/verdict/test_assess.py`
- **Acceptance**
  ```bash
  pytest tests/integration/verdict/test_assess.py -q
  ```
  A firing rule short-circuits the model call entirely (asserted by a mock that fails the test
  if called); `NOT_APPLICABLE` from every rule falls through to retrieval + model; a shadow
  rule persists with `is_shadow=true` and does not suppress the model path for that field;
  the prompt receives only clauses in force on `event_date` in the candidate block.
  **[SPEC]** SQ-17: `check_key` convention is `'R01_...'` or `'F:apr_bps'`, but the §15.2
  example and eval case `EV-TEMPORAL-001` both use `check_key: "R16_contact_window"` for a
  **model-decided** `no_clause_found` where R16 returned `NOT_APPLICABLE`. Suite assertions
  depend on which is right.

### M6-T02 — `validator.py`
- **Status** done — 13/13 unit tests (`tests/unit/verdict/test_validator.py`); ADR-025 fixes
  SQ-18 by running `is_literal_substring` against every citation regardless of role, so a
  context_only excerpt can never survive validation unverified.
- **Depends on** M6-T01
- **Files** `app/verdict/validator.py`, `app/domain/clauses.py` (`by_path`), `tests/unit/verdict/test_validator.py`
- **Acceptance**
  ```bash
  pytest tests/unit/verdict/test_validator.py -q
  ```
  One test per rejection path: path not offered; clause not citable; `effective_from > as_of`;
  `effective_to <= as_of`; excerpt not a literal (whitespace-normalised) substring. Plus:
  a conclusive verdict with zero valid decisive citations downgrades to `no_clause_found` with
  `reason="no_valid_decisive_citation"`; `ambiguous` with one decisive records
  `single_decisive_citation_recorded`; `no_clause_found` carrying decisive citations keeps the
  abstention and demotes them to context. Every rejection writes `audit_event` action
  `citation_rejected` and increments `cc_citation_rejected_total{reason}`.
  **[SPEC]** SQ-18: the `context_only` branch `continue`s **before** the
  `is_literal_substring` check, so a context-only citation's excerpt is never verified. But
  §17.2 computes `hallucinated_citation_rate` over *persisted* citations including
  context-only ones. As written the release-blocking metric can be non-zero by construction —
  a hole in the guardrail, which `CLAUDE.md` §2.1 makes the one unrecoverable defect.
  `ClauseCandidateSet.by_path()` is called here but is not defined in LLD §4.

### M6-T03 — `severity.py`
- **Status** done — 6/6 unit tests (`tests/unit/verdict/test_severity.py`); map completed for
  all 28 registered rule ids (the LLD's own map elides 18 of them with `...`). Signature
  takes `lifecycle_stage` directly rather than `field_key` + a `FieldRegistry` lookup, keeping
  `severity.py` free of a registry dependency — the caller (`assess.py`) already has the
  `FieldSpec` in hand.
- **Depends on** M5-T02, M5-T03
- **Files** `app/verdict/severity.py`, `tests/unit/verdict/test_severity.py`
- **Acceptance**
  ```bash
  pytest tests/unit/verdict/test_severity.py -q
  ```
  The map is **exhaustive** over all registered rule ids (test iterates the registry and
  asserts a key exists for each — the LLD's elided `...` must be completed); `no_clause_found`
  always yields `informational`; a field-decided verdict takes `FIELD_SEVERITY_DEFAULT` by
  lifecycle stage; `VerdictDraft` has no `severity` field (asserted on the model's JSON
  schema) so the model cannot influence it.

### M6-T04 — Assessment persistence and provenance
- **Status** done — DB persistence and provenance done (covered by
  `tests/integration/verdict/test_assess.py`: `corpus_snapshot_id`, `serving_mode`,
  `prompt_version`, per-stage ms/tokens/`cost_usd` all persisted; re-running a check sets
  `superseded_by_id`). The `app/api/v1/assessments.py` HTTP surface was built in the M2/M7
  FastAPI work — `GET /v1/loans/{id}/assessments` joins every citation back to `clause`/
  `regulation_instrument` and returns `verification_status` on each one, non-optional per
  §15.2 (`tests/integration/api/test_documents_and_assessments.py`). SQ-19 (`is_shadow`
  overload) resolved at schema level — `assessment.is_whatif` (ADR-006) is a separate column
  from `is_shadow`, so M7-T03's counts and `include_shadow=false` distinguish the two
  meanings cleanly.
- **Depends on** M6-T02, M6-T03
- **Files** `app/verdict/assess.py`, `app/api/v1/assessments.py`, `tests/integration/verdict/test_persistence.py`
- **Acceptance**
  ```bash
  pytest tests/integration/verdict/test_persistence.py -q
  curl -sf "localhost:8000/v1/loans/$LOAN/assessments" -H "Authorization: Bearer $T" \
    | jq -e '.assessments[].citations[] | has("verification_status")'
  ```
  Every persisted assessment carries `corpus_snapshot_id`, `model_id`, `adapter_id`,
  `serving_mode`, `prompt_version`, per-stage ms, tokens in/out and `cost_usd`; re-running a
  check sets `superseded_by_id` on the prior row rather than deleting it; every citation in
  the API response carries `verification_status` (non-optional per §15.2).
  **[SPEC]** SQ-19: `is_shadow` is overloaded — §11.2 means "unverified clause basis",
  §15.4 means "what-if `as_of` override run". `include_shadow=false` and M7-T03's counts
  cannot distinguish them. Needs a second column.

### M6-T05 — eval harness + `numeric_rules`, `temporal`, `abstention`, `verdict` suites — **shipped, partial**
- **Status** done for the harness itself and 4 of 7 LLD §17.3 suites; `adversarial`,
  `conflicts`, `end_to_end` still open — see ADR-034 (`docs/DECISIONS.md`) for the honest
  scope-reduction rationale. `abstention` **meets** the LLD's ≥40 minimum: 40 cases, 37
  covering every field in `app/schema/fields.yaml` that no registered rule consumes (checked
  directly against `app.rules.registry.all_rules()`), plus 3 more varying doc_type/account
  profile/value on multi-doc_type fields. `numeric_rules` (31) and `temporal` (12) remain
  short of their 60/30 minimums (see M5-T06). `verdict` is new this pass: **16 real cases**
  (short of the LLD's 50-case minimum, an honest partial suite per the project's established
  pattern), the first cases in the suite genuinely requiring real model judgment rather than
  rule arithmetic or a documented no-clause-found abstention — see ADR-046 for the
  construction methodology (deliberately withholding the one fact each rule reads, so
  `MissingFact` forces `NotApplicable` while the underlying clause stays retrieval-eligible,
  driving `assess_fact()`'s real fallthrough path, `check_key="F:<field_key>"`). Built and
  unit-verified **entirely without live LLM calls** per explicit user instruction; not yet
  run against the live API — decisive_citations reflect a documented best-effort assumption
  about what `retrieve_candidates()` will rank top, to be reconciled on the first live run.
- **Depends on** M6-T04
- **Files** `eval/loader.py`, `eval/metrics.py`, `eval/runner.py`, `eval/harness.py`,
  `eval/cases/{numeric_rules,temporal,abstention,verdict}/*.json`,
  `tests/unit/eval/test_eval_{loader,metrics}.py`,
  `tests/unit/eval/test_verdict_suite_fallthrough.py`, `tests/integration/eval/test_harness.py`,
  `reports/`
- **Acceptance (shipped suites)**
  ```bash
  make eval suite=numeric_rules && jq -e '.metrics.hallucinated_citation_rate == 0' reports/eval_numeric_rules_latest.json
  make eval suite=temporal      && jq -e '.metrics.hallucinated_citation_rate == 0' reports/eval_temporal_latest.json
  make eval suite=abstention    && jq -e '.metrics.abstention_correctness == 1.0' reports/eval_abstention_latest.json
  make eval suite=verdict       # not yet run live — pending explicit go-ahead (real spend)
  make eval-report
  ```
  `hallucinated_citation_rate` **exactly 0** on every suite actually run live so far —
  computed over persisted citations, after validation, independently re-derived from the
  database by `eval/runner.py::_resolve_citations` rather than trusted from the validator.
  `tests/unit/eval/test_verdict_suite_fallthrough.py` verifies, with no DB and no LLM call,
  that every `verdict` case's trigger field genuinely falls through every rule that consumes
  it (`NotApplicable` for all of them) rather than being rule-decided.
- **Remaining** `adversarial`/`conflicts`/`end_to_end` suites (including the prompt-injection
  fixture and `forbidden_citations` on every case, not only adversarial ones), plus growing
  `verdict` past 16 cases and its first live run — tracked as follow-up, not a release
  blocker for the harness itself since the harness mechanics are proven end to end against
  real Postgres.

---

# M7 — Conflicts and state

### M7-T01 — `conflicts.yaml`
- **Status** partial — 9/9 unit tests (`tests/unit/conflicts/test_loader.py`). Shipped with
  **4 of the 12** named groups (`apr`, `closure_release_window`, `cure_notice_sequence`,
  `cooling_off` — the last added in M7-T01b), all pointing at real registered rule ids whose
  subject matter matches the group's own fact pattern.
- **Depends on** M2-T01

### M7-T01b — Extend `conflicts.yaml` toward the 12 named groups *(see ADR-029, ADR-035)*
- **Status** partial — added `cooling_off` (4th group): `cooling_off_period_days` is a real
  field on two doc_types (`kfs`, `loan_agreement`), and `R07_cooling_off_disclosed` already
  exists, clause-grounded on `DL2025/p10`, checking exactly this fact pattern.
  The remaining 8 (`sanctioned_amount`, `interest_rate`, `tenor`, `instalment`, `fees`,
  `closure_charge_satisfaction`, `closure_noc_order`, `grievance_officer_contact`) were
  checked directly against the ingested corpus (`SELECT ... FROM clause WHERE text ILIKE
  '%no objection%' OR '%foreclosure%' OR '%closure charge%' ...`) and remain blocked — see
  ADR-035 for the per-group reasoning. Each needs either a new clause the corpus does not
  yet carry, or a formal drop from the LLD's list; neither is guessed at here per CLAUDE.md
  §2.6 and §8.
- **Depends on** M7-T01
- **Files** `app/rules/conflicts.yaml`, `tests/unit/conflicts/test_loader.py`,
  `docs/DECISIONS.md`
- **Acceptance**
  ```bash
  pytest tests/unit/conflicts/test_loader.py -q
  python -c "from app.conflicts.loader import load; assert len(load().groups)==4"
  ```
  No group may point at a rule whose subject matter doesn't match the group's own fact
  pattern — verified for `cooling_off` against `R07_cooling_off_disclosed`.

### M7-T02 — `detector.py`
- **Status** done — 21/21 unit tests (`tests/unit/conflicts/test_detector.py`, pure
  `compare()`) + 4/4 integration tests (`tests/integration/conflicts/test_detector_integration.py`,
  against real persisted `extracted_fact`/`document` rows). Enqueuing `assess_check.delay(...)`
  is explicitly out of scope here — Celery isn't wired yet (M8) — so `detect_for_fact` returns
  the detected conflicts for the caller to act on; `persist_conflicts` writes `fact_conflict`
  rows. Found and fixed one detector-internal bug during testing: date_order comparisons must
  be ordered by the group's own listed member order (earlier member first), not by
  trigger-fact-vs-counterpart-fact — the two are unrelated when the *later*-listed member is
  the one that happens to trigger detection.
- **Depends on** M7-T01, M5-T02

### M7-T03 — `loan_compliance_state` recomputation
- **Status** done — 2/2 integration tests (`tests/integration/verdict/test_state.py`).
  `app/verdict/state.py`'s `recompute_loan_compliance_state` excludes both `is_shadow` and
  `is_whatif` assessments from every count and from `highest_severity` (ADR-006 already gave
  these separate columns, so SQ-19 was resolved at the schema level in M2 — nothing left to
  block on here). Wired into `assess.py`: called once per `assess_fact` invocation, after
  persistence, skipped entirely when `is_whatif=True` so a what-if run never touches real
  state.
- **Depends on** M6-T04, M7-T02

### M7-T04 — `report.py`
- **Status** done — `GET /v1/loans/{id}/report?format=json|pdf` assembles the same
  citation-joined data as `/assessments` (clause path, instrument, effective window,
  `verification_status` per finding), rendered as JSON or a `reportlab`-built PDF; both
  formats carry the not-legal-advice disclaimer, and a visible synthetic-data banner
  whenever any of the loan's documents is `is_synthetic = true`.
- **Depends on** M7-T03
- **Files** `app/verdict/report.py`, `app/api/v1/assessments.py`, `tests/integration/api/test_report.py`
- **Acceptance**
  ```bash
  curl -sf "localhost:8000/v1/loans/$LOAN/report?format=json" -H "Authorization: Bearer $T" | jq -e '.disclaimer|test("Not legal advice")'
  curl -sf "localhost:8000/v1/loans/$LOAN/report?format=pdf" -H "Authorization: Bearer $T" -o /tmp/r.pdf && file /tmp/r.pdf | grep -q PDF
  pytest tests/integration/api/test_report.py -q
  ```
  Both formats carry the synthetic-data banner and the not-legal-advice disclaimer
  (PRD §6.3), every finding's clause path, instrument, effective window and
  `verification_status`.

### M7-T05 — `conflicts` and `end_to_end` suites
- **Status** blocked *(M6-T05)*
- **Depends on** M7-T02, M7-T03
- **Files** `eval/cases/{conflicts,end_to_end}/*.json`, `reports/`
- **Acceptance**
  ```bash
  make eval suite=conflicts  && jq -e '.metrics.verdict_accuracy >= 0.90' reports/eval_latest.json
  make eval suite=end_to_end && jq -e '.case_count >= 20' reports/eval_latest.json
  ```
  ≥25 conflict cases with contradictory document sets; ≥20 end-to-end accounts with an
  expected `loan_compliance_state`.

---

# SESSION CHECKPOINT (resume here)

M0–M2 (all of it, including T04/T05/T06/T06b/T07) and M3–M7 (minus M7-T01b, M7-T04, M7-T05)
are done: 271 tests passing, ruff/black/mypy --strict clean on `app/`. A real FastAPI app
exists (`app/main.py`) with working auth, health checks, document submission with sync
extraction, assessment retrieval, and a `/metrics` endpoint; Celery is wired; boot assertions
run in the lifespan; both halves of LLD §18 (logging and metrics) are done. Nothing is
checked out uncommitted as of the commit that lands this note.

**Next up**: M7-T04 (`report.py` + `/v1/loans/{id}/report`), M6-T05/M7-T05 (the eval harness
and its suites — nothing in `eval/` exists yet at all, this is a from-scratch build: `make
eval`, `eval/cases/*.json`, `reports/eval_*.json`), M7-T01b (the 9 deferred conflict groups,
blocked on new clause-grounded rules), then M8 (deploy — mostly blocked on hosting account
decisions, SQ-20) and M9 (fine-tune comparison).

Two testing patterns worth knowing before touching `app/api/`:
1. Tests drive the app via `httpx.AsyncClient(transport=ASGITransport(app=app))` on the
   pytest-asyncio loop, never `fastapi.testclient.TestClient` — the latter runs the app in a
   separate thread with its own event loop, which collides with this codebase's cached
   module-level SQLAlchemy engine the moment a test also touches the database directly.
2. The LLM client is injected via `Depends(get_llm_client)` (`app/api/deps.py`) specifically
   so tests can override it with `app.dependency_overrides[get_llm_client] = lambda: stub`
   rather than making a real network call — see
   `tests/integration/api/test_documents_and_assessments.py`.

---

# M8 — Deploy, demonstrate, load test

### M8-T01 — Deployment
- **Status** blocked *(SQ-20: hosting accounts)*
- **Depends on** M7-T05
- **Files** `deploy/`, `.github/workflows/deploy.yml`, `docs/RUNBOOK.md`
- **Acceptance**
  ```bash
  # after 60 minutes idle:
  curl -s -o /dev/null -w '%{time_total}\n' https://<live-url>/v1/corpus   # < 2.0
  ```
  Postgres auto-suspend **disabled** (asserted by reading the plan setting and recording it in
  `docs/COSTS.md`); a Redis restart does not lose acknowledged queued work (test: enqueue,
  restart, observe completion); the database plan does not expire.

### M8-T02 — `docs/COSTS.md`
- **Status** blocked *(M8-T01)*
- **Depends on** M8-T01
- **Files** `docs/COSTS.md`
- **Acceptance**
  ```bash
  python scripts/check_costs_doc.py    # exit 0 only if every line has all five fields
  ```
  Per line item: provider, plan, price, idle-suspend behaviour, date checked, source URL.

### M8-T03 — Demonstration page
- **Status** blocked *(M8-T01)*
- **Depends on** M7-T04
- **Files** `app/api/v1/demo.py`, `static/`, `scripts/seed_demo.py`, `Makefile` (`make seed-demo`)
- **Acceptance**
  ```bash
  make seed-demo && curl -sf https://<live-url>/ | grep -q "synthetic"
  npx playwright test tests/e2e/demo.spec.ts
  ```
  Three accounts (clean; APR contradiction + late release; collections-heavy) each load in one
  click and render the document timeline, facts with evidence spans highlighted, conflicts,
  and verdicts expanding to clause text, path, instrument and effective window. Synthetic
  banner and not-legal-advice disclaimer visible without scrolling.

### M8-T04 — Date control wired to the `as_of` override
- **Status** blocked *(M8-T03)*
- **Depends on** M8-T03
- **Files** `app/api/v1/assessments.py`, `static/`
- **Acceptance**
  ```bash
  npx playwright test tests/e2e/temporal_pair.spec.ts
  ```
  Moving the control from 2026-09-03 to 2027-01-03 on the same transcript flips the verdict
  from `no_clause_found` to `violation`; at the earlier date the clause panel shows
  `RBC-AMD2026/p100W` as context with its commencement date and the microfinance limb as
  out-of-scope; the what-if run does not mutate stored event dates or the account's compliance
  state. This is the PRD §11 pair, live.

### M8-T05 — Evidence links from the page
- **Status** blocked *(M8-T03)*
- **Depends on** M8-T03, M8-T08
- **Files** `static/`
- **Acceptance**
  ```bash
  for p in /v1/corpus /v1/eval/latest /reports/loadtest_latest.json; do curl -sf "https://<live-url>$p" >/dev/null || exit 1; done
  ```
  Corpus manifest, latest evaluation report and load-test result all reachable from the page
  without authentication.

### M8-T06 — `loadtest/baseline.js`
- **Status** blocked *(M8-T01)*
- **Depends on** M8-T01
- **Files** `loadtest/baseline.js`, `Makefile` (`make load`), `reports/`
- **Acceptance**
  ```bash
  make load && jq -e '.metrics | has("stage_a_p95") and has("stage_b_p95") and has("stage_c_p95")' reports/loadtest_baseline.json
  ```
  Twenty concurrent submissions held for five minutes; per-stage percentiles, queue depth,
  error rate and cost per document recorded.

### M8-T07 — Break test
- **Status** blocked *(M8-T06)*
- **Depends on** M8-T06
- **Files** `loadtest/break.js`, `reports/`
- **Acceptance**
  ```bash
  k6 run loadtest/break.js && test -f reports/loadtest_break.json
  ```
  Ramp until a stage degrades. The bottleneck is **named with evidence** — the metric series
  and the saturating resource — in `reports/loadtest_break.md`. Expected first candidate is
  frontier-model concurrency (`verdict_model_concurrency`), database connection exhaustion
  second; the point is to measure, not assume.

### M8-T08 — Fix and re-measure
- **Status** blocked *(M8-T07)*
- **Depends on** M8-T07
- **Files** `app/llm/client.py` *(or wherever the bottleneck lands)*, `reports/`
- **Acceptance**
  ```bash
  make load && python scripts/diff_loadtest.py reports/loadtest_baseline.json reports/loadtest_after.json
  ```
  One targeted change. Before and after in `reports/`, with the delta stated as numbers and a
  sentence on what would break next.

---

# M9 — Fine-tune and comparison

### M9-T01 — Training set
- **Status** blocked *(M3-T07)*
- **Depends on** M3-T07, M3-T08
- **Files** `scripts/gen_training_set.py`, `data/train/` *(gitignored)*
- **Acceptance**
  ```bash
  python scripts/gen_training_set.py --n 3000 && python scripts/check_training_set.py
  ```
  2,000–5,000 examples; **every** example labelled synthetic; the checker fails if any example
  overlaps an `extraction_core` eval fixture (train/eval leakage) or matches a real-looking
  identifier pattern.

### M9-T02 — Base-model licence re-verification
- **Status** blocked *(SQ-21)*
- **Depends on** —
- **Files** `docs/DECISIONS.md`
- **Acceptance**
  ```bash
  grep -q "ADR-.*base model" docs/DECISIONS.md
  ```
  Licences of the three candidate Apache-2.0 8–9B bases re-verified **at the moment of the
  fine-tune** (PRD §14 Q7), each with the licence URL and the date checked; the choice and the
  rejected alternatives recorded as an ADR.

### M9-T03 — QLoRA run
- **Status** blocked *(M9-T01, M9-T02, SQ-22: GPU account)*
- **Depends on** M9-T01, M9-T02
- **Files** `training/qlora.py`, `training/config.yaml`, `docs/DECISIONS.md`
- **Acceptance**
  ```bash
  python training/qlora.py --config training/config.yaml   # on the rented GPU
  python scripts/check_adapter.py --path $ADAPTER          # rank == 16, 4-bit, loads in vLLM
  ```
  Rank capped at 16 (serving-portability constraint, HLD §7.3). The adapter artefact is
  retained **outside** the repository (`CLAUDE.md` §6) and its location recorded.

### M9-T04 — `tuned_gpu` serving mode
- **Status** blocked *(M9-T03)*
- **Depends on** M9-T03
- **Files** `app/llm/routing.py`, `app/config.py`, `tests/integration/llm/test_serving_mode.py`
- **Acceptance**
  ```bash
  CC_SERVING_MODE=tuned_gpu pytest tests/integration/llm/test_serving_mode.py -q
  psql "$CC_DATABASE_URL" -c "SELECT DISTINCT serving_mode FROM assessment" | grep tuned_gpu
  ```
  Extraction routes to the vLLM endpoint while verdicts stay on the frontier model;
  `serving_mode` and `adapter_id` are recorded on **every** assessment and every extracted fact.

### M9-T05 — Measured comparison
- **Status** blocked *(M9-T04)*
- **Depends on** M9-T04
- **Files** `reports/`
- **Acceptance**
  ```bash
  CC_SERVING_MODE=tuned_gpu make eval suite=extraction_core
  python scripts/diff_eval.py reports/eval_m3_baseline.json reports/eval_m9_tuned.json --per-field
  ```
  Per-field-key delta against the M3 baseline published, on the same eval set, same corpus
  snapshot. A regression is reported as measured, not hidden (PRD §13).

### M9-T06 — Cost and latency on both paths
- **Status** blocked *(M9-T05)*
- **Depends on** M9-T05
- **Files** `reports/`, `docs/COSTS.md`
- **Acceptance**
  ```bash
  python scripts/breakeven.py --baseline reports/eval_m3_baseline.json --tuned reports/eval_m9_tuned.json
  ```
  Cost per document and p95 latency on `hosted_baseline` and `tuned_gpu`, with the GPU rental
  cost stated; break-even volume computed and printed.

### M9-T07 — `docs/WRITEUP.md`
- **Status** blocked *(M9-T06)*
- **Depends on** M8-T08, M9-T06
- **Files** `docs/WRITEUP.md`
- **Acceptance**
  ```bash
  python scripts/check_writeup_traceability.py   # every numeric figure resolves to a reports/ file
  ```
  Release gate item 6 (PRD §8.2): every figure in the write-up traces to a file in `reports/`.
  The checker fails on any number in the document that it cannot resolve to a report field.

---

## Release gate tracking (PRD §8.2)

| # | Gate | Closed by |
|---|---|---|
| 1 | Live URL, cited verdict under 10 s, no cold start, no signup | M8-T01, M8-T03 |
| 2 | Published per-stage baselines for extraction, retrieval, verdicts | M3-T08, M4-T08, M6-T05 |
| 3 | Measured fine-tune delta with cost per document on both paths | M9-T05, M9-T06 |
| 4 | Full per-stage eval table incl. abstention and adversarial, hallucinated-citation rate 0 | M6-T05, M7-T05 |
| 5 | Load test with a named bottleneck, a fix, before/after numbers | M8-T06, M8-T07, M8-T08 |
| 6 | Written account, every figure traceable to `reports/` | M9-T07 |
