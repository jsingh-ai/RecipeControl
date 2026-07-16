# RecipeControl

RecipeControl is a local, single-user MVP for building immutable time-based break definitions over minute-bucketed OPC-UA samples, generating complete Gantt-style timelines, and labeling individual segments for later training use. It never writes to a PLC or collector table.

## Which instructions should I use?

Use **Production VM: step by step** when RecipeControl will read your collector MySQL database. This is the recommended deployment path. It builds the React application into nginx, runs the API and historical worker in containers, and stores RecipeControl data in its own persistent MySQL volume.

Use **Local development with fixture data** when you only want to evaluate or develop the application without connecting to a collector database.

RecipeControl does not have user authentication. Keep a deployed instance behind a trusted LAN, VPN, firewall, authenticated reverse proxy, or SSH tunnel. Do not expose it directly to the public internet.

## Production VM: step by step

### 1. Prepare the VM

Install Git, Docker Engine, and the Docker Compose plugin. A practical minimum is 4 GB RAM plus enough disk for minute snapshots and database backups.

Confirm that the commands are available:

    git --version
    docker --version
    docker compose version

Your collector MySQL administrator must provide a separate account with **SELECT-only** access to the collector schema. RecipeControl must never use the collector's writable account.

### 2. Clone the repository

Replace the placeholders with the actual repository URL and target directory:

    git clone <repository-url>
    cd <repository-folder>

If the repository is already on the VM:

    cd <repository-folder>
    git branch --show-current
    git status --short
    git pull

Do not pull over uncommitted VM-specific changes. Production secrets belong in the untracked environment file described next, not in source-controlled files.

### 3. Create the production environment file

    cp .env.production.example .env.production
    nano .env.production

Set at least these values:

- **APP_DB_PASSWORD**: a URL-safe password for RecipeControl's writable database user.
- **APP_DB_ROOT_PASSWORD**: a different strong password for the application MySQL root user.
- **SOURCE_DATABASE_URL**: the collector connection URL using its SELECT-only account.
- **CORS_ORIGINS**: the protected browser origin, for example http://recipecontrol.internal.

Leave **ENABLE_LIVE_MODE=false**. Historical mode is the supported workflow.

Choose the source URL that matches where collector MySQL runs.

MySQL on the same Linux VM:

    SOURCE_DATABASE_URL=mysql+pymysql://readonly_user:percent_encoded_password@host.docker.internal:3306/opcua_collector

MySQL on another network host:

    SOURCE_DATABASE_URL=mysql+pymysql://readonly_user:percent_encoded_password@10.20.30.40:3306/opcua_collector

MySQL in another Docker network:

    SOURCE_DATABASE_URL=mysql+pymysql://readonly_user:percent_encoded_password@collector-db:3306/opcua_collector
    COLLECTOR_DOCKER_NETWORK=collector_default

Important: 127.0.0.1 inside a container means that container, not the Linux VM. Use host.docker.internal for MySQL running directly on the VM. Percent-encode special password characters in database URLs. Never commit .env.production.

For a collector in another Docker network, use both Compose files in every Compose command:

    docker compose --env-file .env.production -f docker-compose.prod.yml -f docker-compose.collector-network.yml config --quiet

The remaining steps show the normal VM-host or network-host form. Add the second -f option to each command when using an external Docker network.

### 4. Validate the deployment configuration

This checks interpolation and Compose structure without starting anything:

    docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet

Fix every reported missing variable before continuing.

### 5. Build the production images

    docker compose --env-file .env.production -f docker-compose.prod.yml build

The frontend is built with npm run build and served by nginx. The Vite development server is not used in production.

### 6. Start RecipeControl

    docker compose --env-file .env.production -f docker-compose.prod.yml up -d

On startup, Compose performs these operations in order:

1. Start the private RecipeControl MySQL service.
2. Run Alembic migrations against the RecipeControl application database.
3. Start the FastAPI service and historical worker.
4. Start nginx after the API is healthy.

Only the frontend HTTP port is published. The API and application database remain internal. The collector database is read-only and is never migrated by RecipeControl. The live worker is not started.

### 7. Confirm every service is healthy

    docker compose --env-file .env.production -f docker-compose.prod.yml ps
    curl --fail http://127.0.0.1/health
    curl --fail http://127.0.0.1/api/health

If a service is not healthy, inspect its logs:

    docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 app-db migrate api worker frontend
    docker compose --env-file .env.production -f docker-compose.prod.yml logs -f api worker

### 8. Verify read-only collector access

These diagnostics read collector metadata and samples but do not write collector data:

    docker compose --env-file .env.production -f docker-compose.prod.yml run --rm api recipecontrol-source-smoke health
    docker compose --env-file .env.production -f docker-compose.prod.yml run --rm api recipecontrol-source-smoke diagnostics

Ask the database administrator to verify the collector account grants:

    SELECT CURRENT_USER();
    SHOW GRANTS FOR CURRENT_USER;

The account should have SELECT only on the collector schema. It must not have INSERT, UPDATE, DELETE, CREATE, ALTER, or DROP privileges there.

### 9. Open the application and create the first analysis

From a computer on the protected network, open:

    http://<vm-lan-address>/

Then:

1. Open **Rule Builder** and select the required machine.
2. Create a rule set and draft version.
3. Search for tags, add conditions and groups, then save the draft.
4. Lock the version. Locked versions are immutable.
5. Open **Timeline**, select the machine and locked version, and enter a UTC start and inclusive end minute.
6. Select **Analyze**. The historical worker processes the queued job.
7. When it is complete, inspect the primary and condition lanes.
8. Select a segment to add a Good, Bad, or Unsure label, classification, and note.

If an analysis remains queued, confirm the worker is healthy and inspect the worker logs from step 7.

### 10. Back up before updates

The application database is stored in the persistent recipecontrol_app_db Docker volume. Back it up before every update:

    mkdir -p backups
    chmod 700 backups
    docker compose --env-file .env.production -f docker-compose.prod.yml exec -T app-db sh -c 'exec mysqldump -urecipecontrol -p"$MYSQL_PASSWORD" --single-transaction --routines --triggers recipecontrol' > "backups/recipecontrol-$(date -u +%Y%m%dT%H%M%SZ).sql"
    chmod 600 backups/recipecontrol-*.sql

The full restore procedure is in [Production VM deployment](docs/vm-deployment.md). Never restore this backup into the collector database.

### 11. Pull and deploy a later update

After taking a backup:

    cd <repository-folder>
    git branch --show-current
    git status --short
    git pull
    docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
    docker compose --env-file .env.production -f docker-compose.prod.yml build
    docker compose --env-file .env.production -f docker-compose.prod.yml up -d
    docker compose --env-file .env.production -f docker-compose.prod.yml ps
    curl --fail http://127.0.0.1/api/health

### 12. Restart or stop the application

Safe restart:

    docker compose --env-file .env.production -f docker-compose.prod.yml restart api worker frontend

Stop containers while retaining the database volume:

    docker compose --env-file .env.production -f docker-compose.prod.yml down

Start them again:

    docker compose --env-file .env.production -f docker-compose.prod.yml up -d

Do not use docker compose down -v unless you intentionally want to destroy the RecipeControl application database. For backup/restore, rollback, external-Docker-network, and detailed troubleshooting procedures, see [Production VM deployment](docs/vm-deployment.md).

## Local development with deterministic fixture data

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

Timeline includes inactive locally known machines so their saved analyses remain reviewable. If source synchronization is temporarily unavailable, Timeline shows a warning and continues from the application database. Inactive machines cannot create definitions, analyses, or live sessions.

## Docker development

The Compose stack uses MySQL 8.4 for writable RecipeControl data and the fixture source by default. Replace the `APP_DB_PASSWORD` and `APP_DB_ROOT_PASSWORD` placeholders in the uncommitted `.env` first:

```bash
docker compose up --build
```

Compose refuses to start without those uncommitted passwords. To connect a real source, configure the exact collector URL described in `docs/source-schema.md`.

For a production VM, use the nginx-based image and internal-only API/database stack in `docker-compose.prod.yml`. The complete first-deploy, backup/restore, health, update, rollback, host-MySQL, and external-Docker-network procedures are in [VM deployment](docs/vm-deployment.md). RecipeControl has no user authentication yet; keep production access behind a LAN, VPN, firewall, authenticated gateway, or SSH tunnel.

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
make e2e-visual     # capture 24 deterministic viewport screenshots under docs/screenshots/visual
make e2e-real       # unmocked migrated API + worker + fixture + frontend workflow
make build          # production frontend build
make compose-prod-check # validate production Compose interpolation and structure
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
- During atomic result persistence, the background heartbeat writer stops and the job uses `HISTORICAL_PERSISTENCE_LEASE_SECONDS` (default 900 seconds). This avoids SQLite writer contention while protecting valid MySQL persistence from stale-job reclaim.
- Retired classifications disappear from future choices, but a segment already carrying one may preserve or clear it while its quality label or note is edited.
- Live mode is unavailable: this is expected while `ENABLE_LIVE_MODE=false`; historical analysis remains fully available.
- Source health fails: verify the read-only URL, network path, and exact mapping variables. Errors returned to the browser are intentionally redacted.
- MySQL datetime appears naive: the adapter intentionally attaches UTC because `sampled_at_utc` is authoritative UTC.
- Browser test cannot launch: run `npx playwright install chromium` in `frontend`.
- Vite reports a large chunk: ECharts is the principal bundle cost; this is a performance advisory, not a failed build. Route-level lazy loading is the next optimization.

See [architecture](docs/architecture.md), [segmentation](docs/segmentation-algorithm.md), [source mapping](docs/source-schema.md), [data model](docs/data-model.md), and [live mode](docs/live-mode.md).
