# Specification queries

Points where `ClauseCheck_LLD_v1.0.md` (or the document set as a whole) is internally
inconsistent, unimplementable as written, or silent on something a task needs. Raised before
M1 starts, per the kickoff instruction to say so plainly rather than work around it.

Each entry states what the documents say, why it does not work, and the options. **None is
resolved by guessing.** Where a query blocks a task, `TASKS.md` marks that task `[SPEC]` and
names the query.

Status: `open` · `answered` · `closed`

---

## Blocking — these stop a task from being written correctly

### SQ-04 · `embedding_dimension: 3072` cannot carry an HNSW index
**Status** open · **Blocks** M1-T06, M2-T02, M4-T02

LLD §2 sets `embedding_dimension: 3072` (`text-embedding-3-large`), §3.4 declares
`embedding vector(3072)`, and creates `ix_clause_vec ON clause USING hnsw (embedding vector_cosine_ops)`.

pgvector's `vector` type indexes to a maximum of 2,000 dimensions on both HNSW and IVFFlat.
`CREATE INDEX` on a 3,072-dimension `vector` column fails outright. The migration in M2-T02
cannot run as specified.

Options: (a) `halfvec(3072)` with `halfvec_cosine_ops`, which indexes to 4,000 dimensions at
half precision; (b) request 1,536 or 1,024 dimensions from the embedding API via its
`dimensions` parameter and keep `vector`; (c) a different embedding model at ≤2,000.

Recommendation: **(b) at 1,536**. The corpus is a few hundred clauses — recall is not
dimension-starved at this scale, `vector` stays exact, and boot assertion §2.1 keeps config
and column honest. (a) trades precision for a number we do not need; (c) reopens a settled
decision. Whichever is chosen, `CLAUDE.md` §3 ("vector dimension from config, never
hardcoded") means the migration reads `settings.embedding_dimension` rather than literalising
it, which also makes this reversible.

### SQ-13 · No borrower-class predicate exists, so the defining behaviour cannot be produced
**Status** open · **Blocks** M4-T07, M5-T03, M6-T05, M8-T04

PRD §11 — the behaviour the product is built to demonstrate — requires that on 2026-09-03 the
microfinance contact-hour provision is returned as `context_only`, "annotated as out of scope
for this borrower class". LLD §8.5 step 7 lists "entity scope" as an exclusion reason.

But `APPLICABILITY_SQL` (§8.1) filters on `snapshot_id`, `citable`,
`applies_to_entity_types`, the two effective windows and `status <> 'draft'`. Entity type is
the **lender's** class (`nbfc`), not the borrower's. The microfinance clause is in force on
that date, is citable, and applies to NBFCs — so it passes every predicate and lands in
`candidates`, where the model is free to cite it decisively. Nothing in the schema records
which borrower classes a clause is scoped to. `loan_account.is_microfinance` exists but is
never joined into retrieval.

If both halves of the temporal pair return `violation`, PRD §11's own diagnosis applies: "the
applicability filter is not working and nothing else in the system can be trusted."

Options: (a) add `clause.applies_to_borrower_classes text[]` populated at ingest, add the
predicate to `APPLICABILITY_SQL` against the account's class, and route clauses excluded
*only* by that predicate to `context_only` with reason `borrower_scope`; (b) leave it to the
prompt, which `CLAUDE.md` §2.1 rules out as a guarantee; (c) handle it in R17 alone, which
does not help the model path that actually decides this case.

Recommendation: **(a)**. It is the only option that makes the invariant structural, and the
exclusion reason vocabulary in §8.5 already anticipates it. It adds a column to migration
0005 and a value to populate during M1 parsing, so it is cheapest to decide now.

### SQ-18 · The citation validator does not check context-only excerpts
**Status** open · **Blocks** M6-T02, M6-T05

`validate()` (§10.2) handles the context-only role first:

```
if cit.role == "context_only":
    (kept if cit.clause_path in ctx_ok else rejected).append(cit); continue
```

The `continue` skips the `is_literal_substring` check below it. A context-only citation's
`quoted_clause_excerpt` is therefore never verified against the clause text — the model may
paraphrase or invent it and it will be persisted.

§17.2 defines the release-blocking metric over **persisted** citations: "whose path is absent
from the snapshot OR whose excerpt is not a substring of the clause". That set includes
context-only citations. So `hallucinated_citation_rate` can be non-zero through a path the
validator deliberately does not guard — and §15.2's own example response carries exactly such
a citation (`"...only between 08:00 hours and 19:00 hours..."` on `RBC-AMD2026/p100W`).

This is the defect class `CLAUDE.md` §2.1 calls unrecoverable. The fix belongs in the
validator, not the prompt, and per §10.2's own logic "the fix is in the validator".

Recommendation: run the excerpt check for **every** role; a context-only citation failing it
is rejected and audited with reason `excerpt_not_substring` like any other. Also needs
`ClauseCandidateSet.by_path()`, which §10.2 calls but §4 never defines, and which must resolve
across both `candidates` and `context_only`.

### SQ-23 · Document text has no route from the API process to the worker process
**Status** open · **Blocks** M3-T06, M3-T08, and everything downstream of extraction

§14 forbids document text in a Celery payload — Redis "is not a place customer text may rest"
(`CLAUDE.md` §2.3) — and specifies instead "a single-use, expiring **in-memory** handoff keyed
by the document id, or re-supplied by the caller".

§20.1 and §20.2 both run the API and the worker as **separate processes in separate
containers**. An in-memory handoff in the API process is not reachable from the worker. The
only shared stores are Postgres (where §2.3 forbids the text) and Redis (forbidden by §14
itself). "Re-supplied by the caller" has no endpoint in §15 for a worker to pull from, and
would require the tenant's client to stay online for the duration of an async job.

As specified, Stage A cannot obtain the text it is supposed to extract from.

Options: (a) extract **synchronously** inside the API request and queue only assessment — the
text never leaves the process, at the cost of a longer request and a weaker p95 story;
(b) a short-TTL Redis key holding the text, encrypted at rest with a per-document key, which
is an explicit, documented narrowing of §2.3 rather than a silent one; (c) a
`GET /v1/internal/documents/{id}/text` one-shot endpoint the worker calls back into, which
keeps text in one process but adds an internal auth surface.

Recommendation: **(a) for v1**. It preserves the invariant exactly, and PRD §8.1's p95 target
is per document under 10 s, which synchronous extraction plausibly meets. Record the choice
and the rejected options as an ADR, because this is the invariant a BFSI buyer will ask about.

---

## Correctness — wrong as written, fix is clear but needs sign-off

### SQ-15 · Rules cannot obtain clause text through the specified `FactIndex`
**Status** open · **Blocks** M5-T01, M5-T02, M5-T03

R01 and R16 (§11.3) both call `facts.clause_excerpt("RBC2025/p35")`. §11.1 specifies
`FactIndex` as "a read-only mapping from field key to the latest fact for that key on the
account, with helpers `date_of`, `money_of`, `bps_of`, `flag_of`, `datetime_of`" — no clause
access. Rules are "pure and synchronous. No session, no network", so a rule cannot look the
clause up itself.

Recommendation: pass a pre-resolved `dict[clause_path, str]` of excerpts into `evaluate()`
alongside `facts` and `account`, loaded once per assessment from the active snapshot. This
changes the `Rule` protocol signature, so it must be settled before M5-T01 rather than
retrofitted across 28 rules.

### SQ-16 · R16 reads the wrong clock, and 19:00:00 exactly is undefined
**Status** open · **Blocks** M5-T03, M5-T06

Two separate problems in `r16_contact_window.py`:

1. `ts.timetz().replace(tzinfo=None)` yields the wall time of whatever tzinfo the datetime
   carries. A `timestamptz` read back from Postgres arrives in the session time zone, which is
   UTC unless deliberately set. A 20:10 IST contact becomes 14:40 — inside the window — and
   the rule returns `compliant` for a violation. Fix: `ts.astimezone(ZoneInfo("Asia/Kolkata")).time()`.
2. `WINDOW_OPEN <= t <= WINDOW_CLOSE` makes 19:00:00 exactly **compliant**. §17.3 requires the
   numeric suite to test "18:59/19:00/19:01", but no document states the expected verdict at
   19:00:00. "Between 08:00 hours and 19:00 hours" is genuinely ambiguous in the instrument.

Recommendation: fix (1) unconditionally. For (2), I need your ruling, and it should be
recorded in the rule as a named constant with the reasoning, because it is exactly the kind of
boundary an interviewer will probe. My reading is that 19:00:00 is inside the permitted window
(the restriction bites at 19:00:01), but the corpus text retrieved in M1 may settle it.

### SQ-06 · Three rule clause bases are not valid clause paths
**Status** open · **Blocks** M5-T02, M5-T03, M1-T04

§11.4 gives R02b the basis `RBC2025 §F`, R17 `RBC2025 §H`, and R04 `KFS2024/annexB`.

The canonical format (HLD §4.1) is `{code}/p{para}[/{level2}][/{level3}]`, and §11.1 says
`clause_paths` is "validated against the corpus at boot". `RBC2025 §F` can never resolve — the
parser emits section letters as a display column, never as a path component. Boot assertion
§2.4 will mark both rules shadow permanently, which silently removes R17 from the very
temporal pair it exists to serve. `KFS2024/annexB` has no parser: §6.2 specifies `annexA`
structure only (`para_number='annexA'`, part, row).

Recommendation: resolve all three to real paragraph paths from M1's parse output, and add a
boot-time assertion that every declared `clause_path` matches the canonical path regex — so a
section-letter basis fails loudly at boot instead of degrading to shadow.

### SQ-09 · Boot assertion and `/readyz` contradict each other on a fresh database
**Status** open · **Blocks** M2-T04, M2-T07

Boot assertion §2.2 — "Exactly one `corpus_snapshot` row has `is_active = true`" — is fatal.
M2-T04 requires `/readyz` to **fail** (`CC-503-CORPUS-UNAVAILABLE`) when there is no active
snapshot. A process that exits at boot cannot serve a 503. On a fresh clone, `make dev` brings
up an API container that crash-loops before migrations have been run, and the operator sees a
restart loop rather than the diagnostic the error taxonomy was designed to give.

Recommendation: keep §2.1, §2.3, §2.4 and §2.5 fatal, and demote §2.2 to a readiness check —
the process starts, `/healthz` is green, `/readyz` returns `CC-503-CORPUS-UNAVAILABLE`, and no
work is dequeued until a snapshot is active. That preserves the intent ("refuse to run against
a corpus it was not built for") while keeping the failure legible.

### SQ-08 · The `cc_app` grants reach no tables
**Status** open · **Blocks** M0-T03, M2-T03

§20.1 runs `GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO cc_app` at database
bootstrap. `ON ALL TABLES` grants only on tables that exist at that moment; Alembic creates
every table afterwards. `cc_app` ends up with no privileges and the application cannot read or
write anything.

Recommendation: `ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ... TO cc_app` at bootstrap
(so future tables inherit), plus an explicit re-grant step at the end of migration 0008 for
anything created before the default privileges took effect. The `REVOKE UPDATE, DELETE ON
audit_event` must then run after 0007, not at bootstrap.

### SQ-07 · The field registry count is stated three different ways
**Status** open · **Blocks** M2-T01

§5.3 opens "Sixty-one keys". Its five group headings sum to 32 + 11 + 7 + 21 + 9 = **80**. The
key names actually enumerated come to **82** — the collections group is labelled 21 and lists
23 (`cure_notice_21day_sent_date`, `cure_notice_7day_sent_date` and
`device_restoration_delay_hours` push it over). M2-T01's acceptance criterion is "all 61 keys",
which cannot be written against any of the three numbers.

Recommendation: take the enumerated names as authoritative — they are what the rules and
`pinning.yaml` consume — count them, and correct the prose. I can produce the exact list and
count as the first step of M2-T01; I need you to confirm that the enumerated set is the
intended one and that no key was dropped rather than the count being a typo.

### SQ-17 · `check_key` is used two incompatible ways
**Status** open · **Blocks** M6-T01, M5-T06

§3.5 documents `check_key` as "`'R01_docs_release_30d'` or `'F:apr_bps'`" — a rule id when a
rule decided, a field marker when the model did. But §15.2's example shows
`check_key: "R16_contact_window"` with `decided_by: "model"`, on a date where R16 returns
`NOT_APPLICABLE` and the model handles it. Eval case `EV-TEMPORAL-001` (§17.1) asserts the same
`check_key`.

So either the convention is wrong, or the example and the permanent eval case are. Suite
assertions and `assess_check`'s supersession key both depend on the answer.

Recommendation: keep the rule id as the `check_key` whenever a rule *covers* the field, even
when it declines on the date — it keeps a check's history on one key across the 2027 boundary,
which is what a compliance head wants to see. That means §3.5's `'F:<field>'` form is for
fields no rule covers at all. Confirm and I will correct the convention in §3.5's ORM comment.

### SQ-19 · `is_shadow` carries two unrelated meanings
**Status** open · **Blocks** M6-T04, M7-T03

§11.2: `is_shadow = true` means the rule's clause basis is unverified, so the finding does not
count. §15.4: a `POST /assess` with an `as_of` override persists "with `is_shadow = true`" so a
what-if run does not pollute compliance state.

These are different facts about a row. `include_shadow=false` (§15.2) cannot distinguish them,
and M7-T03's "shadow assessments excluded from counts" is ambiguous about which it excludes.

Recommendation: add `is_whatif boolean NOT NULL DEFAULT false` in migration 0006 and leave
`is_shadow` meaning only "unverified basis".

### SQ-12 · Draft clauses can reach `context_only`, which every eval case forbids
**Status** open · **Blocks** M4-T07, M6-T05

§8.5 step 7 builds `context_only` by re-querying "WITHOUT the date predicates", annotated with
why each was excluded — and lists **"draft"** among the reasons. The validator accepts any
context-only path present in `ctx_ok`. But §17.1 sets
`forbidden_citations: ["RBC-AMD2026-DRAFT/p100W"]` and states `forbidden_citations` is
"asserted on **every** case, not only adversarial ones", and PRD §10 says drafts are ingested
"marked non-citable … so the evaluation suite can assert that draft text is never cited in a
finding".

Recommendation: drop only the two date predicates in step 7; keep `status <> 'draft'` and
`citable` in force. Drafts then stay out of every citation role, and forward-looking review of
draft text is served by `GET /v1/clauses/{path}` rather than by the assessment path.

---

## Smaller corrections

### SQ-10 · The RRF precedence claim is arithmetically a tie
**Status** open · **Affects** M4-T04

§8.4: "With `k = 60` and pinned weight 2.0, a clause appearing first in the pinned list
outranks a clause appearing first in both vector and lexical lists."

`2.0/(60+1) = 0.0327868…` and `1.0/(60+1) + 1.0/(60+1) = 0.0327868…`. Equal. The pinned clause
wins only because the documented tie-break puts pinned first. The behaviour is the intended
one; the stated reason is wrong, and anyone reading §8.4 to justify the weight will find it
does not. Raise `rrf_weight_pinned` (2.5 makes it a genuine margin) or correct the sentence. I
would correct the sentence — the tie-break is deterministic and tested either way.

### SQ-14 · Two suites are required by tasks but absent from the suite table
**Status** open · **Affects** M4-T08, M6-T05

M4-T08 runs "`retrieval` suite", M6-T05 runs "`verdict` … suites", and PRD §8.1 measures four
metrics in a `retrieval` suite and two in a `verdict` suite. §17.3's table lists only
`extraction_core`, `numeric_rules`, `temporal`, `abstention`, `conflicts`, `adversarial`,
`end_to_end`. Neither `retrieval` nor `verdict` appears, so neither has a declared minimum case
count. `eval_case.stage`'s CHECK does allow `'retrieval'`.

Recommendation: add both to §17.3 with minimum sizes — I propose `retrieval` 40 and `verdict`
50 — so M4-T08 and M6-T05 have a size to meet.

### SQ-24 · The CI suite selection is neither fast nor free
**Status** open · **Affects** M0-T04, M6-T05

§17.4: CI runs `numeric_rules`, `temporal` and `abstention` on every pull request, described as
"fast, no extraction". `temporal` and `abstention` are `stage: verdict` cases; abstention cases
are precisely the ones where no rule fires and the frontier model decides. Every pull request
therefore makes model calls and needs a provider key in CI, with per-PR cost.

Recommendation: on pull requests run `numeric_rules` plus the rule-decided subset of `temporal`
(no model call, genuinely fast), and move the model-dependent cases to the nightly run.
Otherwise budget for it explicitly and put the key in CI secrets.

### SQ-05 · Pinned amendment paragraphs are unconfirmed and boot failure is fatal
**Status** open · **Affects** M1-T12, M4-T05, M2-T07

`pinning.yaml` (§7) hard-codes `RBC-AMD2026/p100W`, `/p100X`, `/p100N`, `/p100Q`–`/p100S`. PRD
§14 Q2 records that whether the final amendment preserves the draft's paragraph numbering is
**unconfirmed**. Boot assertion §2.3 is fatal unless `fail_boot_on_pinning_mismatch` is false,
which is "permitted only in `ci`". If M1 finds the amendment renumbered, `local` and `prod`
cannot boot until the table is corrected.

This is the intended design (refuse to run against the wrong corpus) and I am not proposing to
weaken it — flagging it so the M1 → M2 sequencing is deliberate: the pinning table must be
rewritten from M1's parse output before any environment can start.

### Minor, no decision needed
- §3.8 says migration 0005's `downgrade()` "must drop the HNSW index before the table … or the
  drop blocks". `DROP TABLE` removes dependent indexes automatically and does not block. The
  instruction is harmless; the rationale is wrong.
- `severity_for` (§10.3) does `SEVERITY[rule_id]` against a map shown with `...` covering ~10 of
  28 rules — a `KeyError` for the rest, and `registry.get(None)` when `field_key` is null. M6-T03
  asserts exhaustiveness over the registry.
- §12's `assess_check.delay(account_id, group.raises_check)` omits `tenant_id` and `request_id`
  from the §14 signature; with RLS the task fails on its first query.
- `AssessmentResult.telemetry: "StageTelemetry"` (§4) — `StageTelemetry` is never defined.
- `ExtractedFactOut` (§4) uses `UUID` without importing it.
- §5.3's collections group is labelled 21 and lists 23 (see SQ-07).

---

## Needed from you — not in the documents

### SQ-01 · `rbi.org.in` is unreachable from this environment
**Status** open · **Blocks** M1-T02, M1-T09, M1-T10, M1-T11

Measured, not assumed:

```
CONNECT www.rbi.org.in:443 → HTTP/1.1 403 Forbidden   (agent proxy, policy denial)
```

All three RBI hosts tried return 403 at the proxy's CONNECT. M1's real deliverable is
`docs/CORPUS.md` reporting what the parsers found **in the live regulator sources**, and
promoting or correcting each instrument's verification status against them. That cannot be
done from here.

What I can do meanwhile: build and golden-file test the parsers, chunker, reference extractor
and snapshot machinery against checked-in fixture documents, so M1 is one `make ingest` away
from completion once sources are reachable. What I will not do is fill the gap with
plausible-sounding clause text (`CLAUDE.md` §8).

Options: allow `rbi.org.in` in the environment's network policy; or fetch the five documents
yourself and place them in `data/raw/` with their hashes recorded in `corpus_sources.yaml`,
which §6.1 already anticipates as the manual path for at least one instrument.

### SQ-02 · Source URLs for the five instruments
**Status** open · **Blocks** M1-T01

No document in the set carries the actual URLs. PRD §10 gives circular numbers and dates;
`corpus_sources.yaml` needs resolvable addresses, and HLD §4.4 says to prefer the regulator's
HTML view over the PDF.

### SQ-03 · Model and embedding API keys
**Status** open · **Blocks** M1-T06, M3-T06, M3-T08 and every later eval run

The kickoff readiness table says "Nothing blocks M1 and M2 beyond a local Docker installation"
— but M1-T06 is `embed.py`, and embedding the corpus needs an embedding key. So M1 needs one
key earlier than the table implies. A frontier key is not needed until M3.

### SQ-11 · Model identifiers are placeholders
**Status** open · **Blocks** M0-T02

`app/config.py` ships `extract_model: str = "<frontier-model-id>"`,
`verdict_model: str = "<frontier-model-id>"`, `classify_model: str = "<small-model-id>"`. Real
LiteLLM model ids required, along with which provider they route to.

### SQ-20 · Hosting accounts · **Blocks** M8-T01
Per LLD §20.2: two small always-on instances, managed Postgres with pgvector and auto-suspend
**disabled**, managed Redis, Indian region. ~$20–24/month.

### SQ-21 · Base-model licence verification timing · **Blocks** M9-T02
PRD §14 Q7 requires licences re-verified at the moment of the fine-tune. Confirm the three
Apache-2.0 8–9B candidates you want checked.

### SQ-22 · GPU rental account · **Blocks** M9-T03
~$3–5 for the QLoRA run, ~$10–15 for benchmark runs.
