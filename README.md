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

Run these three processes in separate terminals:

```bash
make backend
make worker
make frontend
```

Open `http://localhost:5173`. API documentation is at `http://localhost:8000/docs`; readiness details are at `http://localhost:8000/api/health`.

The fixture source supports any UTC range. The timeline form includes the requested preset from `2026-06-11 19:50` through `2026-06-23 14:20` UTC. Historical analyses are queued; keep `make worker` running. Live mode is experimental and disabled by default.

## Docker development

The Compose stack uses MySQL 8.4 for writable RecipeControl data and the fixture source by default. Replace the `APP_DB_PASSWORD` and `APP_DB_ROOT_PASSWORD` placeholders in the uncommitted `.env` first:

```bash
docker compose up --build
```

Compose refuses to start without those uncommitted passwords. To connect a real source, configure the exact collector URL described in `docs/source-schema.md`.

## Live source configuration

The default remains `SOURCE_ADAPTER=fixture`. To use the authoritative `opcua_collector` schema:

1. Create a read-only MySQL account restricted to `SELECT`.
2. Set `SOURCE_ADAPTER=mysql` and `SOURCE_DATABASE_URL` only in `.env` or the process environment.
3. Keep `APP_DATABASE_URL` on a separate writable database/account. Startup rejects reuse of the source username on the same host and port.
4. Run `make seed`, then inspect `/api/health` and paginated tag search.

Verify the source account while connected as that account:

```sql
SHOW GRANTS FOR CURRENT_USER;
```

It should have `SELECT` only on the collector schema. MySQL 8.0 or newer is required for the supported application and integration-test schema.

The adapter contains only the fixed `machines`, `tags`, and `tag_samples` reads documented below. Query values are bound, the session time zone is `+00:00`, and Alembic uses only `APP_DATABASE_URL`. Never point `APP_DATABASE_URL` at the collector database.

Read-only source smoke commands:

```bash
.venv/bin/recipecontrol-source-smoke health
.venv/bin/recipecontrol-source-smoke diagnostics
.venv/bin/recipecontrol-source-smoke machines
.venv/bin/recipecontrol-source-smoke tags --machine 1 --query temperature --limit 20
.venv/bin/recipecontrol-source-smoke range --machine 1
.venv/bin/recipecontrol-source-smoke dry-run --machine 1 --tag 10 --kind numeric --start 2026-06-23T14:15:00Z --inclusive-end 2026-06-23T14:20:00Z
```

The dry run reports `2026-06-23T14:21:00+00:00` as the exclusive query end and never opens the application database.

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
make test-mysql-up  # start isolated collector/application MySQL test services
make test-mysql     # exact collector schema + application MySQL historical workflow
make test-mysql-down # remove isolated MySQL test services and volumes
make test-mysql-all # run the three MySQL steps with cleanup on exit
make e2e            # Playwright critical workflow
make e2e-real       # unmocked migrated API + worker + fixture + frontend workflow
make build          # production frontend build
make checks         # every check above plus Playwright
make verify         # local checks, real-stack browser flow, and isolated MySQL tests
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
10. Archive the definition and verify the saved analysis, exact-minute details, trends, classifications, notes, and labels remain available.

The same source tag may be selected in multiple conditions. Each condition receives its own stable condition ID, so `Temperature > 250` and `Temperature increases by 5 over 10 minutes` remain distinct break reasons.

## Live-mode status

Historical analysis is the supported MVP. `ENABLE_LIVE_MODE=false` and `VITE_ENABLE_LIVE_MODE=false` are the defaults. The API refuses new live sessions and the frontend hides the live start control while disabled. Do not enable live labeling until the remaining boundary/annotation and late-arrival behavior in `docs/live-mode.md` is fully tested.

## Troubleshooting

- `no such table`: run `make migrate` with the same `APP_DATABASE_URL` used by the API and workers.
- Analysis remains queued: start `make worker`; inspect the analysis job status and server logs.
- A worker that stops heartbeating is reclaimed after `STALE_JOB_TIMEOUT_SECONDS`; jobs fail with a sanitized message after `HISTORICAL_JOB_MAX_ATTEMPTS`.
- Live mode is unavailable: this is expected while `ENABLE_LIVE_MODE=false`; historical analysis remains fully available.
- Source health fails: verify the read-only URL, network path, and exact mapping variables. Errors returned to the browser are intentionally redacted.
- MySQL datetime appears naive: the adapter intentionally attaches UTC because `sampled_at_utc` is authoritative UTC.
- Browser test cannot launch: run `npx playwright install chromium` in `frontend`.
- Vite reports a large chunk: ECharts is the principal bundle cost; this is a performance advisory, not a failed build. Route-level lazy loading is the next optimization.

See [architecture](docs/architecture.md), [segmentation](docs/segmentation-algorithm.md), [source mapping](docs/source-schema.md), [data model](docs/data-model.md), and [live mode](docs/live-mode.md).
