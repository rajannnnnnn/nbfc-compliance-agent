# Deployment requirements brief — paste this to get proposals

Use this document as the prompt/context when asking any tool (including another
Claude session) to propose a deployment plan. It states what the product is, what
components it needs, and what constraints the deployment must respect. Paste it
verbatim; then have it fill in a component-by-component hosting proposal, in the
same table shape as §1 of `docs/DEPLOYMENT_PLAN.md`, and correct any pricing claim
if the platform doesn't actually offer what's stated.

---

## What ClauseCheck is

ClauseCheck is a retrospective RBI-compliance auditor for Indian NBFCs. A lender's
own compliance team submits loan documents and collections-call transcripts. The
system extracts typed facts, resolves which RBI provisions were in force on the
event date, retrieves the governing clauses, and returns a cited verdict
(`compliant` / `violation` / `ambiguous` / `no_clause_found`). It is not
borrower-facing and not in any credit or payment decision path — a backend audit
tool, exposed today only as an HTTP API (no frontend yet).

## What has to run in production

| Component | Role | Hard requirements |
|---|---|---|
| **Postgres 16 + pgvector** | System of record: clauses, loans, facts, assessments, audit log | Needs `vector` extension, row-level security, and the ability to run Alembic migrations against it. ~211 real clauses today, small dataset (MBs, not GBs). |
| **Redis** | Celery broker/result backend only — never a datastore of record | Standard `redis://`/`rediss://` protocol. Low throughput at demo traffic. |
| **API process** | FastAPI + Uvicorn, async | All slow work (extraction, retrieval, verdict) is meant to go to a queue, not run inline in the request — see the queue requirement below. |
| **Background worker** | Celery worker consuming `extract`/`assess`/`maintenance` queues | Needs a long-lived process that can pull from the queue continuously — this is the component that rules out a pure request-triggered "serverless function" platform (Lambda/Vercel/Cloudflare Workers can't run a persistent queue consumer). |
| **LLM + embeddings** | Gemini via LiteLLM (`gemini-2.5-flash`, `gemini-embedding-001`, dim 1536) | Already wired, already has a working API key. Not part of the hosting decision — just needs outbound HTTPS from wherever the API/worker run. |

## Constraints the deployment must respect

1. **Cost target: as close to $0/month as honestly possible.** This is a portfolio/demo
   deployment, not a funded production service. State the realistic floor plainly —
   don't round an always-on VM down to "$0" if it isn't actually free.
2. **"Serverless" claims must be accurate.** If a proposed platform is actually a
   billed-by-the-second VM (e.g. Fly.io) rather than true pay-per-invocation
   serverless, say so explicitly rather than calling it serverless.
3. **The Celery worker needs a long-lived process.** Call out clearly if a component
   choice can't satisfy this (e.g. a pure serverless-functions platform), and either
   propose a real always-on/queue-consuming option for the worker, or propose the
   demo-only tradeoff of folding worker logic inline into the API request handler
   (explicitly flagged as a deviation from the real architecture, acceptable only
   for a demo).
4. **No real borrower data — ever.** Every fixture and demo document is synthetic and
   marked `is_synthetic = true`. This is a non-negotiable already in `CLAUDE.md` §2.4
   and must render as a visible banner on any public demo surface.
5. **No document bytes persisted anywhere** (Postgres, disk, object storage, logs,
   queue payloads) — only hashes, source URIs, typed values, and capped redacted
   quoted spans. This constrains what "just store it in S3" type suggestions can do.
6. **Cold starts should be named, not hidden.** If a scale-to-zero DB or auto-stopping
   VM is proposed, state the actual cold-start latency tradeoff instead of implying
   an always-warm experience.
7. **No credentials/secrets committed to the repo.** Deployment secrets go through the
   target platform's secret manager, referenced in setup steps, never hardcoded.
8. **Must not require Docker Hub image pulls** to validate locally first, if the
   proposal is meant to be dry-run tested in this sandbox — Docker Hub is
   proxy-blocked in the current dev environment (apt-based installs of Postgres/Redis
   work fine as a local fallback).

## What "done" looks like for a deployment proposal

- A live URL serving `/healthz`, `/readyz`, and a real `/v1/loans` → document → assessment
  flow end-to-end.
- A stated, itemized monthly cost per component, with free-tier limits named precisely
  (not "generous free tier" — actual numbers: storage GB, request/command quotas, etc.).
- A visible synthetic-data banner on any public-facing output.
- Concrete, ordered setup steps (create project → set secrets → run migrations →
  ingest corpus → smoke test), assuming the reader has this repository checked out
  locally and nothing else.

## What NOT to include in a proposal

- Do not propose fixing any of the accuracy metrics in `docs/METRICS_TRACKING.md` —
  that work is explicitly paused; this is a deployment-only exercise.
- Do not propose authentication/rate-limiting as part of the base plan; note it as a
  "should add before wide sharing" caveat instead, since it's out of scope for the
  initial cost-minimization plan.
