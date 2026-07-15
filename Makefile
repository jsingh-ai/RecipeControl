.PHONY: setup migrate seed backend worker live-worker frontend lint typecheck test test-backend test-frontend test-mysql-up test-mysql test-mysql-down test-mysql-all test-e2e e2e e2e-real build checks verify source-smoke

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

e2e-real:
	cd frontend && npm run e2e:real

test-e2e: e2e e2e-real

test-mysql-up:
	docker compose -f docker-compose.test.yml up -d --wait

test-mysql:
	TEST_COLLECTOR_MYSQL_URL=mysql+pymysql://root@127.0.0.1:3308/opcua_collector_test .venv/bin/pytest backend/tests/test_mysql_integration.py
	TEST_APP_MYSQL_URL=mysql+pymysql://root@127.0.0.1:3309/recipecontrol_test .venv/bin/pytest backend/tests/test_migrations.py backend/mysql_tests/test_app_mysql_workflow.py

test-mysql-down:
	docker compose -f docker-compose.test.yml down -v

test-mysql-all:
	bash scripts/run_mysql_tests.sh

source-smoke:
	.venv/bin/python -m recipecontrol.source_smoke health

build:
	cd frontend && npm run build

checks: lint typecheck test build e2e

verify: checks e2e-real test-mysql-all
