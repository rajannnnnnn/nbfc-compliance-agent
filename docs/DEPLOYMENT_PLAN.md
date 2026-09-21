# Deployment plan — close-to-zero-cost, public demo

Goal: a live URL, always-on enough to be usable, costing ~$0/month at demo traffic levels.
This is for portfolio/demo purposes — see the honest caveats in §4 before calling it
"production." Metrics work is paused; this plan does not touch `app/`.

## 1. Component-by-component hosting choice

| Component | Choice | Why | Free tier limit that matters |
|---|---|---|---|
| Postgres 16 + pgvector | **Neon** | Native pgvector support, generous free tier, serverless (scales to zero) | Sleeps after idle → first request after sleep is slow (~1-2s cold connect). 0.5GB storage free — plenty for a 211-clause corpus. |
| Redis (Celery broker) | **Upstash** | Serverless Redis, pay-per-request beyond free quota, works over standard `redis://`/`rediss://` | 10,000 commands/day free — fine for low demo traffic, would need upgrade under real load |
| API (FastAPI/Uvicorn) | **Fly.io** (1 shared-cpu-1x/256MB Machine) | Runs a real long-lived process (needed for the Celery worker anyway — see below) | **Corrected**: Fly is NOT serverless and has no free tier — it's a VM billed by the second, $0.0027/hr ($1.94/mo if left running 24/7). With `auto_stop_machines = "stop"` + `auto_start_machines = true` in `fly.toml`, the Machine stops when idle and only bills for seconds actually spent handling requests — realistically pennies/month at demo traffic, but not literally $0, and each wake-from-stop is a real cold start (hundreds of ms–seconds), same tension as release gate #1's "no cold start" |
| Celery worker | **Same Fly.io Machine as the API**, second process | Avoids paying for a second machine; Fly supports multiple processes per app via `[processes]` in `fly.toml` | Auto-stop doesn't apply cleanly to a worker process (it needs to stay up to consume queue messages) — either accept the worker Machine stays running (~$1.94/mo, the realistic floor for this plan) or accept that queued jobs wait until the next inbound HTTP request wakes the shared Machine. For a low-traffic demo, cheapest honest option: run API and worker as one combined process (skip the separate worker process, call extraction/assessment inline in the request handler) — deviates from the "queue everything" architecture rule, acceptable tradeoff for a demo, not for the real product. |
| LLM + embeddings | **Gemini** (already configured: `gemini-2.5-flash`, `gemini-embedding-001`) | Already wired via LiteLLM, already has a working key | Free tier rate limits (RPM/RPD) — fine for demo traffic, will 429 under a burst; `app/llm/client.py` already retries with backoff |

**Total realistic cost, corrected**: Neon and Upstash free tiers are real and cost $0. Fly.io is not free — realistic floor is **~$2/month** for one always-on shared-cpu-1x Machine (needed to keep the Celery worker consuming the queue), or closer to $0 if you accept the inline-processing tradeoff above and let the Machine auto-stop between requests. Not "$0 guaranteed," but genuinely close to it either way — corrects the too-optimistic "$0" framing in the original version of this plan.

## 2. Concrete steps, in order

1. **Neon**: create a project, enable the `vector` extension, run `scripts/db_bootstrap.sql` + `alembic upgrade head` against it, then `make ingest` once locally pointed at the Neon URL (this activates the corpus snapshot in the real deployed DB).
2. **Upstash**: create a Redis database, copy its `rediss://` URL into `CC_REDIS_URL`.
3. **Fly.io**: `fly launch` in this repo (it will detect the existing `Dockerfile`), set secrets (`fly secrets set CC_DATABASE_URL=... CC_REDIS_URL=... CC_LLM_API_KEY=... CC_EMBEDDING_API_KEY=...`), add a `[processes]` block to `fly.toml` so one VM runs both `api = "uvicorn app.main:app --host 0.0.0.0 --port 8000"` and `worker = "celery -A app.tasks.celery_app worker -Q extract,assess,maintenance -c 2"`.
4. **Corpus**: confirm `RBC2025`'s real text (already ingested locally this session) travels with the deployed DB — either re-run `make ingest` against Neon directly, or `pg_dump`/`pg_restore` the local corpus tables (`clause`, `regulation_instrument`, `corpus_snapshot`) into Neon so the real text doesn't need re-extracting.
5. **Demo banner**: confirm the frontend/API response visibly marks every result as synthetic/demo data per CLAUDE.md §2.4 before this is public — this is not optional, it's the thing standing between "cool demo" and "someone thinks this gives real compliance advice."
6. **Smoke test**: hit `/healthz`, `/readyz`, and one real `/v1/loans` + document + assessment flow against the deployed URL before sharing it.

## 3. What this plan deliberately does NOT do

- Does not fix any of the metrics in `docs/METRICS_TRACKING.md` — paused per instruction.
- Does not solve the Celery-worker-needs-a-long-lived-process constraint any other way (a truly serverless function platform like Vercel/Cloudflare Workers can't run Celery workers at all — this is why Fly.io, not a pure-serverless platform, is the pick for compute).
- Does not add authentication/rate-limiting for public exposure — worth adding before wide sharing, since Gemini API costs are attached to your key.

## 4. Honest caveats to state alongside the demo link

- Regulation text is real for `RBC2025` only (211 clauses, still formally `unverified`); everything else (`DL2025`, `KFS2024`) is placeholder. Say this explicitly, don't let a visitor assume otherwise.
- `verdict_accuracy` on judgment-requiring cases is measured at 31% — don't claim high accuracy; do claim "zero hallucinated citations, measured" (that one's real and strong).
- Cold-start-free is not guaranteed on Neon's free tier after idle — release gate #1's "<10s, no cold start" claim would need a keep-alive ping or an upgrade to state honestly.
