.PHONY: dev migrate revision ingest corpus-verify test test-unit test-integration \
        eval eval-report lint fmt load seed-demo down

dev:
	docker compose up --build

down:
	docker compose down -v

migrate:
	alembic upgrade head

revision:
	alembic revision --autogenerate -m "$(m)"

ingest:
	python -m app.corpus.service ingest --activate

corpus-verify:
	python -m app.corpus.service verify

test:
	pytest

test-unit:
	pytest -m "not integration"

test-integration:
	pytest -m integration

eval:
	python -m eval.harness --suite $(suite)

eval-report:
	python -m eval.harness --report-latest

lint:
	ruff check app/ eval/ tests/
	black --check app/ eval/ tests/
	mypy app/

fmt:
	ruff check --fix app/ eval/ tests/
	black app/ eval/ tests/

load:
	k6 run loadtest/baseline.js

seed-demo:
	python -m scripts.seed_demo
