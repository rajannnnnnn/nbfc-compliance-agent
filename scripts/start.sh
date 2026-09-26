#!/bin/bash
set -e

redis-server --bind 127.0.0.1 --port 6379 --save "" --appendonly no &
REDIS_PID=$!

celery -A app.tasks.celery_app worker -Q extract,assess,maintenance -c 2 --loglevel=info &
CELERY_PID=$!

# Backend binds to loopback only — it is never reached directly from outside this
# machine. The gateway (below) is the sole public-facing process.
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

uvicorn app.gateway:gateway --host 0.0.0.0 --port 8080 &
GATEWAY_PID=$!

# If any one of these dies, the container must exit too — otherwise the surviving
# processes keep running with a silently broken sibling (e.g. the gateway staying
# "healthy" while proxying to a dead backend), and Fly's own crash-restart never
# triggers because its main process never actually stopped.
wait -n "$REDIS_PID" "$CELERY_PID" "$BACKEND_PID" "$GATEWAY_PID"
exit 1
