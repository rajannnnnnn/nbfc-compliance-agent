#!/bin/sh
set -e

redis-server --bind 127.0.0.1 --port 6379 --save "" --appendonly no &

celery -A app.tasks.celery_app worker -Q extract,assess,maintenance -c 2 --loglevel=info &

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
