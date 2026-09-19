# ClauseCheck — High-Level Design

| | |
|---|---|
| **Document** | High-Level Design (HLD) / System Architecture |
| **Product** | ClauseCheck |
| **Version** | 1.0 |
| **Date** | 19 September 2026 |
| **Status** | Approved for build |
| **Upstream** | `ClauseCheck_PRD_v1.0.md` |
| **Downstream** | `ClauseCheck_LLD_v1.0.md` |

This document establishes the architecture, the component boundaries, and the design
decisions that constrain implementation. It does not specify code. Table definitions,
function signatures, prompt text, algorithms and API payloads are in the LLD.

---

## 1. Architectural overview

```
                     ┌────────────────────────────────────────┐
   compliance   ────▶ │  FastAPI gateway                       │
   analyst           │  auth · tenant scope · idempotency      │
                     └──────────────┬─────────────────────────┘
                                    │ enqueue
                                    ▼
                     ┌────────────────────────────────────────┐
                     │  Redis — broker + result backend        │
                     └──────────────┬─────────────────────────┘
              ┌────────────────────┴──────────────────────┐
              ▼                                            ▼
   ┌──────────────────────┐                   ┌──────────────────────┐
   │ queue: extract       │                   │ queue: assess        │
   └──────────┬───────────┘                   └──────────┬───────────┘
              │                                          │
   ┌──────────▼───────────┐  ┌──────────────────┐  ┌─────▼────────────────────┐
   │ STAGE A              │  │ STAGE B          │  │ STAGE C                  │
   │ parse → classify →   │─▶│ applicability →  │─▶│ rules → model → citation │
   │ extract → redact →   │  │ pinning →        │  │ validator → severity →   │
   │ span-verify          │  │ vector+lexical → │  │ persist                  │
   │                      │  │ fusion           │  │                          │
   └──────────┬───────────┘  └────────┬─────────┘  └─────┬────────────────────┘
              │                       │                  │
              │            ┌──────────▼──────────────────▼──────────┐
              └───────────▶│  PostgreSQL 16 + pgvector              │
                           │  facts · clauses · assessments ·       │
                           │  conflicts · audit · eval              │
                           └──────────────┬─────────────────────────┘
                                          ▼
                                ┌────────────────────┐
                                │ conflict detector  │
                                │ (deterministic)    │
                                └────────────────────┘
```

Three stages, separate queues, joined only by rows in Postgres.

## 2. The three-stage decomposition and why it exists

This is the load-bearing decision; everything else follows from it.

**Stage A — extraction — is closed-schema and legally ignorant.** It reads one document
and emits typed facts against a fixed registry. It never reasons about law. Two
consequences: the task is narrow enough to fine-tune a small open-weight model on, and it
is narrow enough to evaluate with exact-match metrics.

**Stage B — retrieval — is mostly deterministic.** A field key plus an event date resolves
through a pinning table to candidate clause paths. Vector and lexical search widen recall;
they are not the primary mechanism.

**Stage C — verdict — is the only place legal reasoning happens.** It runs on a hosted
frontier model and its output passes through a code validator that rejects any verdict
whose citations do not resolve.

The alternative — one prompt that reads a document and returns violations — is
undebuggable. When it is wrong you cannot tell whether it misread the document, retrieved
the wrong rule, or reasoned badly, so you cannot improve it. Separation is what makes each
stage independently measurable, and measurement is the product's core claim.

## 3. Stage responsibilities

### 3.1 Stage A — extraction

Normalise to text (PDF extraction with an OCR fallback triggered on low character density
per page). Classify document type if not supplied, declining rather than guessing at low
confidence. Extract the field subset for that type under a schema-constrained prompt
validated against a generated model. Capture, per fact, a character span and a
PII-redacted quotation. Drop and count any fact whose quotation does not appear in the
source — the **span-grounding check**, the cheapest available hallucination detector.
Normalise values to typed forms: dates to ISO-8601, money to integer paise, rates to
integer basis points. Record required-but-absent fields explicitly, because a missing
disclosure is a finding.

Output carries no judgement fields. That boundary is the architecture.

### 3.2 Stage B — retrieval

1. **Applicability filter**, mandatory and not bypassable: clauses whose instrument applies
   to the entity type and whose effective window contains the event date, excluding
   instruments superseded as of that date and instruments marked non-citable.
2. **Rule pinning**: a maintained field-key-to-clause-path map, validated against the
   ingested corpus at process start. A pinned path absent from the corpus is a hard boot
   failure — this is how the system refuses to run against a corpus it was not built for.
3. **Vector recall** over clause embeddings, with the applicability filter applied as a
   SQL predicate rather than post-filtered.
4. **Lexical recall** over clause text. Numeric and unit tokens survive lexical search far
   better than embedding search, and the highest-precision obligations in this domain are
   numeric.
5. **Reciprocal rank fusion** across the three sources with pinned results boosted, each
   candidate retaining its provenance so evaluation can attribute recall to a mechanism.

### 3.3 Stage C — verdict

Rules run first. Where a deterministic rule covers the check and fires conclusively, its
verdict stands and no model is called — this covers most of the numeric and date surface,
exactly and freely.

Everything else goes to the frontier model with the fact, the candidate clauses each
labelled with its path, and a rubric requiring either a citation from the candidate set or
an explicit finding of no applicable clause. Citing outside the candidate set and reasoning
from general knowledge of Indian lending law are both forbidden.

The response then passes the **citation validator**, in code: every cited path must exist
in the candidate set, resolve to a live clause row, and have an effective window containing
the event date. A conclusive verdict carrying zero valid citations is converted to no
applicable clause and the failure is recorded. This is the guardrail, and its being code
rather than prompt text is the point.

Severity comes from a static map keyed on rule or field, never from the model, so it stays
stable across model versions.

### 3.4 The four verdicts

| Verdict | Meaning | Citation requirement |
|---|---|---|
| `compliant` | A clause in force on the event date governs the fact and the fact satisfies it | ≥1 decisive |
| `violation` | A clause in force on the event date governs the fact and the fact breaches it | ≥1 decisive |
| `ambiguous` | Governing clauses exist but conflict, or application is genuinely unsettled | ≥2, or 1 plus recorded reason |
| `no_clause_found` | No provision in force on the event date governs the fact | 0 decisive; near-miss clauses attached as context |

`no_clause_found` is a feature, not a fallback. It is evaluated as its own suite.

## 4. The regulation corpus

The corpus is the component most likely to be wrong and is therefore built to be
checkable rather than built to look complete. Instrument list, references, dates and
verification statuses are in the PRD §10; this section covers the model.

### 4.1 Clause identity

RBI instruments in this family do **not** use decimal clause numbering. Both principal
instruments number paragraphs in a single continuous series across the whole document;
chapters and lettered sections are navigational headings only.

- Digital Lending Directions: chapters I–VII, paragraphs 1–30 continuous, sub-clauses
  lower-roman, third level parenthesised letters.
- Responsible Business Conduct Directions: chapters I–V, paragraphs 1–109 continuous,
  sub-clauses parenthesised numerals, then letters, with notes as lower-roman. Amendments
  insert lettered paragraphs.

Canonical identifier: `{instrument_code}/p{para}[/{level2}][/{level3}]`.

Real: `DL2025/p9/ii`, `RBC2025/p30/1`, `RBC-AMD2026/p100W/4`, `KFS2024/annexA/part2/3`.
Not real, and forbidden anywhere in the codebase: `DL2025/Ch.IV/4.2(a)`.

Chapter is retained as a display column, not as part of the identifier, because paragraph
numbers are globally unique within an instrument.

### 4.2 Temporal model

Every clause carries an effective window. Every retrieval takes an as-of date, which is the
event date of the fact being judged — not today, and not the upload date. Retrieval without
one raises; there is no default.

The corpus holds four temporal layers simultaneously: provisions in force since May 2025,
provisions in force since November 2025, a notified amendment commencing January 2027, and
a draft that may never commence. A system indifferent to this produces confidently wrong
answers in both directions — citing provisions that had not started, and missing provisions
that had.

Supersessions are stored as records rather than implied by absence, so the system can
answer "why did you not cite the 2022 guidelines" with a row.

### 4.3 Cross-instrument references

The digital lending instrument does not restate the Key Facts Statement field list; it
incorporates another circular by reference. Cross-references are therefore modelled as
explicit edges, and retrieval follows incorporation edges one hop. Without this, the system
can establish that a Key Facts Statement was issued but not whether it was complete.

### 4.4 Ingest and versioning

Fetch from a recorded source URL, preferring the regulator's HTML view over the PDF (the
PDF host serves an anti-bot challenge to automated fetches and the HTML is structurally
cleaner). Hash the source. Segment with an instrument-specific parser keyed to the
numbering convention. Chunk at the leaf clause, prepending the parent paragraph's opening
sentence where the leaf is too short to stand alone — a bare `(a) thirty days;` is
meaningless without its stem and embedding it alone destroys retrieval. Handle annexes
separately: tabular annexes chunk row-wise with headers repeated; worked numeric
illustrations chunk whole, because splitting a computation produces nonsense. Embed.
Resolve cross-references. Write a snapshot recording every source URL, hash, retrieval
time, parser version, embedding model and chunk count.

Every assessment records the snapshot it ran against, which is what keeps historical
findings reproducible. A separate verification pass re-fetches sources and reports drift
without mutating anything; it runs weekly in continuous integration, because a
consolidated master direction can be updated underneath the system without notice.

## 5. Deterministic rules

Twenty-seven rules over typed facts: pure functions, no I/O, no model, unit-testable at
boundaries. Each declares the clause paths it implements, the fields it consumes, and the
window in which it is valid — so a rule whose clause is not yet in force simply does not
fire, through the same applicability filter that governs retrieval.

Nine rules are pure date or money arithmetic and are therefore exact. These carry the
precision story. Coverage spans property-document release timing and delay compensation,
APR consistency and computation, penal-charge form and capitalisation, cooling-off
disclosure, disbursal and repayment routing, lending-service-provider fee incidence,
grievance-officer disclosure and escalation timelines, offshore data deletion, biometric
prohibition, recovery-agent pre-notification, contact windows under both the current and
incoming rulebooks, call-recording retention, agent certification, third-party contact,
social-media disclosure, visit pre-intimation, device-restriction preconditions and
restoration compensation, and Key Facts Statement validity and reproduction.

Rules whose clause basis rests on an instrument not yet verified against a regulator-hosted
source run in **shadow mode**: they compute and record but do not emit a citable verdict.
Shadow mode is a property of the rule registry, not a branch scattered through the rules.

A rule verdict beats a model verdict for the same check. Disagreements are recorded as a
standing evaluation signal, and in practice are the fastest way to find both bad rules and
bad prompts.

## 6. Cross-document conflict detection

A single loan generates documents that must agree with each other, and contradictions among
a lender's own documents are among the most common real findings in this domain.

**This is a rule, not an agent.** An earlier design had a planner deciding when to re-read
prior documents. It was removed: an open-ended planner cannot be tested, because no
assertion can be written about what it will do, and the evaluation suite is the product.

The replacement is explicit. Every fact write consults a declared set of conflict groups —
sets of document-type and field-key pairs that must agree, with an operator and tolerance.
Comparison is on normalised values. A mismatch writes a conflict record and enqueues
re-assessment of exactly the checks touching that group, not a full re-run of the account.
Scoping is what keeps cost bounded and behaviour predictable.

Twelve groups in v1, covering APR, sanctioned amount, interest rate, tenor, instalment,
fees, three closure-timeline orderings, cure-notice ordering, grievance-officer contact
details, and cooling-off period.

A conflict is not itself a verdict. It raises a check, and the check produces the cited
verdict — because what is unlawful is not that two numbers differ but the disclosure
failure the difference evidences.

## 7. Model layer

### 7.1 Division of labour

Extraction is closed-schema transduction over one document type at a time: narrow output
space, no reasoning, high volume, and — for the in-VPC deployment path — it must run inside
a customer's own network. That is the right shape for a small fine-tuned open-weight model.

Verdicts require reading statutory language against facts and deciding applicability. That
stays on a hosted frontier model. Fine-tuning a small model for legal reasoning over a
corpus that changes underneath it buys little, is expensive to redo on every amendment, and
makes the most consequential output the least inspectable part of the system.

### 7.2 Base model selection

An Apache-2.0 licensed 8–9B instruct model. Final pick by benchmark on the extraction
evaluation set; the licence is the gate and the benchmark is the tiebreak.

Llama is excluded on licence grounds rather than quality. Its community licence requires
prominent attribution, requires derived models to carry a name prefix, incorporates an
acceptable-use policy that would flow down to every customer in an in-VPC contract, and
imposes a monthly-active-user threshold. For a product whose selling point includes
shipping weights into a regulated customer's network, an Apache-2.0 base removes an entire
class of contractual negotiation for no capability loss. Separately, there is currently no
small dense model in the current Llama generation, so the only in-range option is a 2024
model.

### 7.3 Fine-tune

QLoRA, 4-bit, rank 16, on synthetic extraction examples generated from templated document
families with deliberate variation in layout, phrasing, currency and date formatting, and
OCR-style noise. Rank is capped at 16 beyond regularisation reasons: the one provider
verified to serve customer adapters on shared per-token infrastructure enforces that
maximum, and staying within it preserves the option.

At the planned data scale, renting a GPU and using a managed fine-tuning API differ by
under five dollars, so the decision is made on portability rather than price: **rent the
GPU and own the adapter**, because a managed API binds the adapter to that provider's
base-model list and serving path, and an adapter that cannot ship into a customer's network
defeats the reason for choosing an open-weight base at all.

### 7.4 Serving modes, and an honest constraint

Per-token serverless serving of customer adapters has largely left the market. One major
provider has discontinued it and now serves adapters only on dedicated endpoints; another
documents that adapters cannot be deployed to serverless at all; a third's standalone
product is no longer documented. The one verified exception caps rank at 16 and supports
only four base models, none of them a current Apache-2.0 9B.

There is therefore no route to per-token serving of the chosen adapter at the target
hosting budget. The deployment reflects that rather than concealing it.

| Mode | Extraction | Verdict | Used for |
|---|---|---|---|
| `hosted_baseline` | frontier model, prompted | frontier model | the always-on public demonstration |
| `tuned_gpu` | adapter on a rented GPU via vLLM | frontier model | benchmark runs; the volume SaaS tier |
| `on_prem` | adapter on customer GPU via vLLM | customer endpoint or larger local model | customers who cannot send text out |

The demonstration runs the baseline because it must answer instantly at any hour with no
idle GPU cost. The adapter's accuracy, cost and latency come from benchmark runs on the
same evaluation set, published with the rental cost stated. Mode is recorded on every
assessment, so no result is ambiguous about which stack produced it.

### 7.5 Client boundary

All model calls route through one client behind a single module. No provider SDK is imported
elsewhere. The client owns routing by stage and mode, timeouts, bounded retries with
jitter, a per-provider circuit breaker, structured-output enforcement with one repair
attempt, token and cost accounting, and prompt-cache keys for clause text recurring across
calls. A provider outage degrades to a queued retry and a pending assessment, never to an
uncited verdict.

## 8. Data posture

Three options were considered. Offsets alone are smallest but break the audit trail the
moment a tenant's document moves, and an offset without text cannot be reviewed by a human.
A full copy is off the table. **Redacted spans** is the choice: the minimal literal
substring evidencing each fact, PII-redacted, under a hard cap of fifteen per cent of source
characters across all spans for a document, enforced at write time with longest-first
truncation recorded.

Persisted: content hash, tenant source pointer, typed normalised values, redacted
quotations within cap, character offsets, and the full assessment and audit trail.

Never persisted: original bytes, full text, images, page renders, OCR intermediates, raw
prompts containing document text, or queue payloads containing text. Tasks pass
identifiers; workers read from Postgres and write results back.

Redaction runs deterministically before every write over identifier-shaped, account-shaped,
name, phone, email and address patterns. It applies to raw values and quotations, never to
normalised values for non-PII types — a date or an APR must survive intact or the rules
cannot run. Fields that are inherently non-sensitive, such as the lender's own published
grievance-officer number, are declared redaction-exempt in the field registry rather than
special-cased in code.

Retention is per-tenant: a nightly job removes facts and document rows past the window
while retaining assessments with their citations, which are the compliance record the
tenant needs to keep.

## 9. Tenancy and isolation

Row-level security on every tenant-scoped table, with the application connecting as a
non-superuser role so the policies are enforced rather than advisory. Tenant identity is
resolved from the bearer token at the gateway and set as a session variable that the
policies read. Cross-tenant access is therefore a database-level impossibility rather than
an application-level convention.

## 10. Evaluation architecture

Each stage is measured separately, because an end-to-end accuracy number hides where the
errors are and makes improvement guesswork.

**Extraction** — per-field exact match on normalised values, precision and recall as a set
task, absence accuracy, span-grounding rate, and type-normalisation error rates reported
separately for dates, money and rates, because those are where extraction quietly fails.
Per field key, not only in aggregate; the aggregate is dominated by easy fields and the
compliance-bearing fields are the hard ones.

**Retrieval** — recall at 1, 4 and 8 of the decisive clause, mean reciprocal rank, pinning
hit rate, applicability precision (a filter bug shows up here and nowhere else), and
attribution by source, which is how you learn whether the vector index earns its
complexity.

**Verdict** — accuracy overall and per class with the confusion matrix, since the errors are
asymmetric; citation validity rate, which is 100% by construction and any shortfall means
the validator has a hole; hallucinated-citation rate, which must be exactly zero and is a
release blocker rather than a metric to improve; abstention correctness as its own suite,
because it is the behaviour most likely to regress when the model is made "better"; and
rule-model divergence.

**Suites** — extraction core, numeric rules at boundaries, temporal pairs across
commencement dates, abstention, conflicts, adversarial, and end-to-end. The adversarial
suite matters specifically because a loan agreement is attacker-controlled text from the
system's point of view: a document can contain an instruction to mark the account
compliant, and the correct behaviour is to extract that sentence as text and be entirely
unmoved by it. The suite asserts that.

Any change to a prompt, model, chunker or pinning table requires an evaluation run, and the
task summary states the delta.

## 11. Deployment topology

Two always-on small instances (gateway and worker), a managed Postgres with pgvector and
auto-suspend **disabled**, and a managed Redis. Indian region. No object storage, because no
documents are stored.

Auto-suspend must be off: the default on serverless Postgres in this price band is
suspension after five minutes idle, which turns the first request after a quiet hour into a
multi-second cold start. A demonstration that stalls when an evaluator opens it has failed
at the only moment that mattered.

Free tiers that spin down are disqualified — a service sleeping after fifteen idle minutes
with a minute to wake, a free database that expires thirty days after creation, a free Redis
that loses all data on restart. Any one of the three makes the deployment unfit for purpose.

Target is under twenty-five dollars a month running, with the fine-tune and benchmark GPU
time as one-off costs. Every price is recorded with its source and check date, because these
figures drift.

## 12. Observability

Metrics: request rate and latency by endpoint, queue depth and task latency per stage,
per-stage percentiles, model latency and error rate by provider, token and cost counters by
stage and model, verdict distribution, citation-validation failure rate, span-grounding
failure rate, rule-model divergence, and corpus drift status.

Logs: structured JSON with a request identifier propagated from gateway through queue into
the model client, so a single verdict is traceable end to end. Identifiers, counts,
durations, hashes, verdicts and clause paths only.

Traces: spans across the three stages. The span tree for one assessment is also the clearest
artefact for explaining the architecture.

Alerts: two, deliberately — citation-validation failures above zero over five minutes, and
sustained queue depth. More alerts on a solo-operated system become noise, and muted alerts
are worse than none.

## 13. Load testing

Three phases. **Baseline** at twenty concurrent submissions held for five minutes, recording
per-stage percentiles, queue depth, error rate and cost per document; this is the published
number. **Break**, ramping until a stage degrades — the expected first bottleneck is
frontier-model concurrency, with database connection exhaustion under worker fan-out a close
second, and the point is to find out rather than assume. **Fix and re-measure**, applying one
targeted change and recording before and after.

Candidate fixes in likely order: a bounded semaphore on model concurrency with queue-level
backpressure instead of unbounded retries; a connection pooler or async pool cap in front of
the database; batching retrieval across a document's facts into one round trip; prompt-caching
clause text that repeats within a batch.

The deliverable is not a throughput figure. It is the bottleneck, how the measurement found
it, the fix, the improvement, and what would break next.

## 14. Demonstration surface

A single page served from the same deployment, no signup. An honest banner stating that all
documents are synthetic and that output is cited findings for internal review rather than
legal advice. Three prepared accounts — one clean, one with an APR contradiction and a late
document release, one collections-heavy — each loadable in a click, showing the document
timeline, extracted facts with evidence spans highlighted, detected conflicts, and verdicts
expandable to the cited clause text, path, instrument and effective window.

The centrepiece is a date control. The same collections transcript, assessed as of a date the
visitor chooses. Moving it across the January 2027 commencement changes the verdict from no
applicable clause to violation, with the clause panel showing which provision commenced and
which was scoped to microfinance only. That interaction demonstrates temporal applicability,
citation grounding and principled abstention in about four seconds, which is roughly the
attention a portfolio system gets.

Also linked: the live corpus manifest with hashes, the latest evaluation report, and the load
test result — so a visitor can check the claims without asking.

## 15. Architectural decisions of record

| # | Decision | Rejected alternative | Rationale |
|---|---|---|---|
| 1 | Three stages joined by database rows | One monolithic prompt | Per-stage measurement; independent failure attribution |
| 2 | Facts carry no judgements | Extraction emits findings | Keeps extraction closed-schema, fine-tunable, exactly evaluable |
| 3 | Citation validation in code | Prompt-level instruction | A prompt cannot guarantee an invariant |
| 4 | Mandatory as-of date on retrieval | Timeless corpus | Four concurrent temporal layers; wrong in both directions otherwise |
| 5 | Deterministic conflict trigger | Agentic planner | An open-ended planner cannot be asserted about in a test |
| 6 | Paragraph-continuous clause paths | Decimal clause paths | Matches the instruments as printed; decimal paths would not resolve |
| 7 | Redacted spans, no document bytes | Full copy, or offsets only | Auditable without holding customer data |
| 8 | Apache-2.0 base model | Llama community licence | Removes attribution, naming, AUP flow-down and MAU constraints for in-VPC sale |
| 9 | Three named serving modes | Claim the fine-tune serves the demo | Per-token adapter serving no longer exists at this budget |
| 10 | Rules before models | Model for every check | Nine obligations are arithmetic; arithmetic should be exact and free |
| 11 | Drafts ingested, marked non-citable | Omit drafts | Enables forward review and lets the suite prove drafts are never cited |
| 12 | Public corpus manifest | Internal only | Makes the product's central claim externally checkable |
