# RecipeControl contributor guide

## Layout

- `backend/recipecontrol/domain`: pure segmentation types and engine; no HTTP, ORM, or source SQL imports.
- `backend/recipecontrol/source`: read-only source protocol, deterministic fixture, and the only live collector mapping module.
- `backend/recipecontrol/models.py`: writable RecipeControl ORM only.
- `backend/recipecontrol/api.py`: FastAPI endpoints.
- `backend/recipecontrol/worker.py` and `live_worker.py`: persisted historical/live processors.
- `backend/alembic`: application-database migrations.
- `frontend/src`: React/TypeScript product UI.
- `backend/tests`, `frontend/src/test`, `frontend/e2e`: automated verification.
- `docs`: architecture, algorithm, source mapping, data model, and live semantics.

## Coding and safety rules

1. Treat collector tables as read-only. Source SQL belongs only in `source/mysql.py` and must remain parameterized for values.
2. Never commit `.env`, credentials, raw connection URLs, or production identifiers.
3. Keep timestamps UTC-aware and minute-aligned; selected API end minutes are inclusive but engine/persistence intervals are half-open.
4. Preserve engine independence from FastAPI and SQLAlchemy.
5. Saved rule versions and generated segment boundaries are immutable through public APIs.
6. Add migrations for application-schema changes. Never migrate the source collector.
7. Preserve deterministic latest-row selection and Decimal numeric comparisons.
8. Use accessible text/patterns as well as color.

## Verification

Run `make lint`, `make typecheck`, `make test`, `make build`, and `make e2e`; `make checks` runs the complete set. Run `SOURCE_ADAPTER=fixture make migrate seed` before a manual fixture smoke test.

