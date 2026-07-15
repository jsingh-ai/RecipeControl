# RecipeControl

RecipeControl is a local, single-user MVP for building immutable time-based break definitions over minute-bucketed OPC-UA samples, generating complete Gantt-style timelines, and labeling individual segments for later training use. It never writes to a PLC or collector table.

## Quick start with deterministic fixture data

Prerequisites: Python 3.12+, Node 20+, npm, and optional Docker Compose.

```bash
cp .env.example .env
make setup
make migrate
make seed
```

Run these four processes in separate terminals:

```bash
make backend
make worker
make live-worker
make frontend
```

Open `http://localhost:5173`. API documentation is at `http://localhost:8000/docs`; readiness details are at `http://localhost:8000/api/health`.

The fixture source supports any UTC range. The timeline form includes the requested preset from `2026-06-11 19:50` through `2026-06-23 14:20` UTC. Historical analyses are queued; keep `make worker` running. Live sessions need `make live-worker`.

## Docker development

The Compose stack uses MySQL 8.4 for writable RecipeControl data and the fixture source by default. Replace the `APP_DB_PASSWORD` and `APP_DB_ROOT_PASSWORD` placeholders in the uncommitted `.env` first:

```bash
docker compose up --build
```

Compose refuses to start without those uncommitted passwords. To connect a real source, also configure all source mapping variables described below and in `docs/source-schema.md`.

## Live source configuration

No `db.py` or source schema existed in this repository, so the default is deliberately `SOURCE_ADAPTER=fixture`. To map the real read-only collector:

1. Create a read-only MySQL account restricted to `SELECT`.
2. Set `SOURCE_ADAPTER=mysql` and `SOURCE_DATABASE_URL` only in `.env` or the process environment.
3. Fill every `SOURCE_*_TABLE` and `SOURCE_*_COLUMN` setting using discovered real identifiers. Optional units may be omitted.
4. Run `make seed`, then inspect `/api/health` and tag search.

The MySQL adapter validates identifiers and binds all values. It issues only `SELECT` statements. Alembic uses only `APP_DATABASE_URL`. Never point `APP_DATABASE_URL` at the collector database.

## Commands

```bash
make setup          # create venv and install Python/Node dependencies
make migrate        # alembic upgrade head
make seed           # import machine metadata from selected source adapter
make backend        # FastAPI development server
make worker         # persisted historical worker
make live-worker    # live shadow worker
make frontend       # Vite development server
make lint           # Ruff format/check and ESLint
make typecheck      # mypy and TypeScript
make test-backend   # Pytest unit/integration suite
make test-frontend  # Vitest/Testing Library suite
make e2e            # Playwright critical workflow
make build          # production frontend build
make checks         # every check above plus Playwright
```

First-time Playwright setup:

```bash
cd frontend
npx playwright install chromium
```

Run a single persisted job or live tick without a long-running process:

```bash
.venv/bin/recipecontrol-worker --once
.venv/bin/recipecontrol-live-worker --once
```

Downgrade the application schema:

```bash
.venv/bin/alembic downgrade base
```

## Manual fixture acceptance path

1. Open Rule Builder, choose Fixture Line 1, and create a definition.
2. Add one or more groups. A representative rule is `(Temperature > 250 for 5 minutes AND Pressure < 40 for 2 minutes) OR (Alarm Code = 12 AND Motor Running = false)`.
3. Save/lock it, then return to Timeline and select the same machine/version.
4. Apply the June 11–23 preset and Analyze. Wait for the worker to mark it complete.
5. Inspect the continuous primary lane, condition lanes, Data Gap pattern, and delta Insufficient History recovery when a delta condition is included.
6. Click an exact point, verify the default 15-minute trend, add Speed temporarily, label the segment, create a classification, and save a multiline note.
7. Reload the saved analysis and verify the label. Retire the classification and confirm the existing segment keeps its snapshot.
8. Analyze the same range again and choose Open Existing or Create New.
9. Toggle UTC/Central and verify daylight-aware `America/Chicago` presentation.
10. Start Live, observe the active dashed segment, pause auto-follow, confirm processing continues, and stop the session.

## Troubleshooting

- `no such table`: run `make migrate` with the same `APP_DATABASE_URL` used by the API and workers.
- Analysis remains queued: start `make worker`; inspect the analysis job status and server logs.
- Live heartbeat is stale: start `make live-worker` and confirm all processes share `APP_DATABASE_URL`.
- Source health fails: verify the read-only URL, network path, and exact mapping variables. Errors returned to the browser are intentionally redacted.
- MySQL datetime appears naive: the adapter intentionally attaches UTC because `sampled_at_utc` is authoritative UTC.
- Browser test cannot launch: run `npx playwright install chromium` in `frontend`.
- Vite reports a large chunk: ECharts is the principal bundle cost; this is a performance advisory, not a failed build. Route-level lazy loading is the next optimization.

See [architecture](docs/architecture.md), [segmentation](docs/segmentation-algorithm.md), [source mapping](docs/source-schema.md), [data model](docs/data-model.md), and [live mode](docs/live-mode.md).
