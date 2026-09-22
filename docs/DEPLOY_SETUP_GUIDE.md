# Deploy setup guide — you run these, not Claude

Claude cannot sign up for Neon/Fly.io or hold your API keys — these steps need your
own accounts and billing. This is the exact, ordered command list. Total cost: ~$1.94/month
(one Fly Machine, running api+worker+redis together) + variable Gemini usage, $0 for Neon.

## 0. Prerequisites

- A GitHub-connected terminal with this repo checked out, OR your own machine with the repo cloned.
- `flyctl` installed: `curl -L https://fly.io/install.sh | sh`

## 1. Neon (Postgres + pgvector) — free

1. Sign up at neon.tech, create a project (choose a region close to `bom` — Mumbai/Singapore).
2. In the Neon SQL editor, run: `CREATE EXTENSION IF NOT EXISTS vector;`
3. Copy the connection string it gives you (starts `postgresql://...`). This is your `CC_DATABASE_URL`.
4. From your local checkout, point Alembic at it and migrate:
   ```bash
   export CC_DATABASE_URL="postgresql+asyncpg://<neon-connection-string-without-sslmode-in-path>"
   alembic upgrade head
   ```
5. Run the corpus ingest against this same DB so the real RBC2025 clauses (and placeholders
   for the rest) are live:
   ```bash
   make ingest
   ```

## 2. Redis — self-hosted on the same Fly Machine, no external service needed

`fly.toml` now runs a third process, `redis`, alongside `api` and `worker`, all on one
Machine — `redis-server` bound to `127.0.0.1:6379`, no persistence (`--save '' --appendonly
no`, since Redis here is only a Celery broker/result backend, never a datastore of record
per CLAUDE.md). `CC_REDIS_URL` is already set to `redis://localhost:6379/0` in `fly.toml`'s
`[env]` block — nothing to sign up for, nothing to configure, skip straight to step 3.

## 3. Fly.io (API + worker + redis, one Machine) — ~$1.94/mo

`fly.toml` is already committed in this repo, configured for one `shared-cpu-1x`/512MB
Machine running the `api`, `worker`, and `redis` processes together (kept as one Machine
deliberately — separate Machines would multiply the cost).

```bash
fly auth login
fly launch --no-deploy          # detects fly.toml + Dockerfile, creates the app, do NOT let it provision its own Postgres/Redis
fly secrets set \
  CC_DATABASE_URL="<neon connection string>" \
  CC_LLM_API_KEY="<your Gemini key>" \
  CC_EMBEDDING_API_KEY="<your Gemini key>"
# CC_REDIS_URL is not a secret here — it's already set in fly.toml's [env] block
# to redis://localhost:6379/0, since Redis runs on the same Machine.
fly deploy
```

Do **not** run `fly ips allocate-v4` — the free shared IPv4 + IPv6 that `fly launch` assigns
by default is sufficient and keeps cost at ~$1.94/mo. A dedicated IPv4 costs an extra $2/mo
and isn't needed here.

## 4. Custom subdomain (GoDaddy)

1. `fly certs add yourdemo.yourdomain.com`
2. In GoDaddy DNS, add a CNAME: `yourdemo` → `clausecheck-demo.fly.dev`
3. `fly certs check yourdemo.yourdomain.com` until it shows issued.

## 5. Smoke test

```bash
curl https://clausecheck-demo.fly.dev/healthz
curl https://clausecheck-demo.fly.dev/readyz
# then one real /v1/loans -> document -> assessment flow per the API docs
```

Confirm the response includes the synthetic-data banner (CLAUDE.md §2.4) before sharing the
link publicly.

## 6. Caveats to state alongside the link

- Real regulation text: `RBC2025` only, 211 clauses, still formally `unverified`. Everything
  else (`DL2025`, `KFS2024`) is placeholder — say so.
- `verdict_accuracy` on judgment-requiring cases is currently ~31% — don't claim high
  accuracy; the honest, strong claim is "zero hallucinated citations, measured."
- First request after any idle period may be slower (Neon free-tier cold connect).
