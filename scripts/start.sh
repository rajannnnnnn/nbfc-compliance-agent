#!/bin/sh
set -e

redis-server --bind 127.0.0.1 --port 6379 --save "" --appendonly no &

celery -A app.tasks.celery_app worker -Q extract,assess,maintenance -c 2 --loglevel=info &

# Backend binds to loopback only — it is never reached directly from outside this
# machine. The gateway (below) is the sole public-facing process.
uvicorn app.main:app --host 127.0.0.1 --port 8000 &

exec uvicorn app.gateway:gateway --host 0.0.0.0 --port 8080
