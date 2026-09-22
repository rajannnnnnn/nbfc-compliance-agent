# Server requirements — for provisioning a VM (EC2 / GCP Compute Engine / any equivalent)

Paste this to whatever tool is generating your VM config (Gemini, a Terraform script, etc.)
so it provisions the right machine for ClauseCheck.

## What has to run on this one box

- **Postgres 16 + pgvector extension** — system of record (clauses, loans, facts, verdicts, audit log). Small dataset today (~211 real clauses, a few hundred MB max).
- **Redis 7** — Celery broker/result backend only, not a datastore of record. Low throughput.
- **API process**: `uvicorn app.main:app --host 0.0.0.0 --port 8000` (FastAPI, async).
- **Background worker**: `celery -A app.tasks.celery_app worker -Q extract,assess,maintenance -c 2 --loglevel=info` — must run continuously alongside the API, not as a one-off job.

All four processes run on the same machine for this deployment (not split across separate hosts).

## Minimum instance spec

- **vCPU**: 2 (burstable/shared is fine — this is low-traffic demo load, not production scale)
- **RAM**: 1 GB minimum, 2 GB preferred (Postgres + Redis + Uvicorn + Celery worker together on 512MB is too tight)
- **Disk**: 20 GB SSD (OS + Postgres data + logs; corpus data itself is small)
- **OS**: Ubuntu 22.04 LTS or 24.04 LTS
- **Network**: needs outbound HTTPS (for Gemini API calls via LiteLLM) and inbound TCP 443/80 (public HTTPS for the API) and 22 (SSH for admin) open to your IP only, not `0.0.0.0/0`, for SSH specifically.
- **Public IPv4**: required (for pointing a GoDaddy subdomain CNAME/A record at it).

## Software to install on first boot

```bash
sudo apt-get update
sudo apt-get install -y postgresql-16 postgresql-16-pgvector redis-server python3.11 python3.11-venv nginx certbot python3-certbot-nginx
```

- **nginx** — reverse proxy in front of Uvicorn, terminates TLS (via certbot/Let's Encrypt), forwards to `127.0.0.1:8000`.
- **certbot** — free TLS cert for the GoDaddy subdomain once DNS is pointed at this machine's IP.
- Python deps installed via `pip install -e .` from this repo (see `pyproject.toml`), inside a venv.

## Process supervision

Both `uvicorn` and the `celery worker` must survive reboots and restart on crash — use **systemd** unit files (not a bare `nohup`/`screen` session), one for each:
- `clausecheck-api.service` → runs the uvicorn command above
- `clausecheck-worker.service` → runs the celery worker command above

Both should have `Restart=always` and start after `network.target` and `postgresql.service`/`redis-server.service`.

## Environment variables the app needs (as systemd `Environment=` or an `.env` file)

- `CC_DATABASE_URL` — `postgresql+asyncpg://user:pass@localhost:5432/dbname`
- `CC_REDIS_URL` — `redis://localhost:6379/0`
- `CC_LLM_API_KEY` — Gemini key
- `CC_EMBEDDING_API_KEY` — Gemini key
- `CC_ENV=production`

## Security / firewall rules

- Port 22 (SSH): restrict to your own IP, not open to the world.
- Port 443/80: open to the world (this is the public API).
- Postgres (5432) and Redis (6379): **not** exposed externally — both should only be reachable from `localhost`/loopback, since they run on the same box as the app.

## Non-negotiable from this project's own rules (CLAUDE.md)

- No real borrower data ever touches this machine — only synthetic, `is_synthetic=true` fixtures.
- No document bytes persisted (Postgres, disk, or logs) — only hashes, typed values, redacted spans.
- Every deployment must visibly mark responses as synthetic/demo data before being shared publicly.
