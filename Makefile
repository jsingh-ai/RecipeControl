.PHONY: setup migrate seed backend worker live-worker frontend lint typecheck test test-backend test-frontend e2e build checks

setup:
	python3 -m venv .venv
	.venv/bin/pip install -e '.[dev]'
	cd frontend && npm install

migrate:
	.venv/bin/alembic upgrade head

seed:
	.venv/bin/python -m recipecontrol.seed

backend:
	.venv/bin/uvicorn recipecontrol.api:app --reload --host 127.0.0.1 --port 8000

worker:
	.venv/bin/recipecontrol-worker

live-worker:
	.venv/bin/recipecontrol-live-worker

frontend:
	cd frontend && npm run dev

lint:
	.venv/bin/ruff format --check backend
	.venv/bin/ruff check backend
	cd frontend && npm run lint

typecheck:
	.venv/bin/mypy backend/recipecontrol
	cd frontend && npm run typecheck

test-backend:
	.venv/bin/pytest backend/tests

test-frontend:
	cd frontend && npm test

test: test-backend test-frontend

e2e:
	cd frontend && npm run e2e

build:
	cd frontend && npm run build

checks: lint typecheck test build e2e

