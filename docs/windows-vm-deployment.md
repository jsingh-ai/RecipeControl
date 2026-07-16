# Native Windows VM deployment

This guide supplements the numbered deployment procedure in the repository README. RecipeControl runs without containers: MySQL is a Windows service or network service, FastAPI serves the compiled React SPA and API, and a separate Python process runs historical jobs.

## Process layout

| Process | Purpose | Network exposure |
| --- | --- | --- |
| MySQL | Writable RecipeControl application schema | Localhost or restricted database network |
| FastAPI/Uvicorn | React SPA, API, and health endpoints | TCP 8000 on protected network |
| Historical worker | Claims and computes queued analyses | No listening port |

The collector MySQL connection is outbound and SELECT-only. The live worker is not part of this deployment.

## Required files

- .env: production configuration and secrets; ignored by Git
- frontend\dist: compiled SPA created by npm run build
- logs\api.log: API output when started without -Console
- logs\worker.log: historical worker output when started without -Console
- backups: operator-managed application database dumps

All launch scripts resolve the repository root from their own location, so Task Scheduler does not depend solely on its current directory.

## Startup order

After MySQL is healthy:

1. Run scripts\windows\Invoke-Migrations.ps1.
2. Start scripts\windows\Start-Api.ps1.
3. Confirm /health and /api/health.
4. Start scripts\windows\Start-Worker.ps1.

The launch scripts do not create databases or run migrations automatically. This keeps production schema changes explicit.

## Health interpretation

GET /health confirms that Uvicorn is running and serving the built frontend.

GET /api/health reports:

- api: FastAPI is running
- app_database: the writable RecipeControl database is reachable
- source_database: the read-only collector source is reachable
- ready: all current checks succeeded

A temporary source failure does not erase the local machine catalog or saved analyses. Historical browsing remains possible, while new source-dependent operations may be unavailable.

## MySQL locations

For MySQL on the Windows VM, use 127.0.0.1. For a network server, use its private DNS name or IP. Restrict MySQL listener, account host grants, and firewalls to the required endpoints.

Do not reuse one credential for APP_DATABASE_URL and SOURCE_DATABASE_URL. Startup rejects the same username on the same MySQL host and port.

## Task Scheduler reliability settings

Create separate API and historical-worker tasks under a dedicated non-administrator account. For each task:

- trigger at startup with a short delay
- run whether the user is logged on or not
- restart one minute after failure
- do not start a second instance
- do not set a short maximum run duration
- record task failures in Windows Task Scheduler history

The worker has its own stale-job recovery, bounded retry, heartbeat, and persistence-lease behavior. Task Scheduler should restart a crashed worker but must not launch overlapping worker instances under the same task.

## Updating

Before each update:

1. Back up the RecipeControl application schema.
2. Record the current Git revision.
3. Stop API and worker tasks.
4. Pull the intended branch.
5. Run Install-RecipeControl.ps1 to update dependencies and rebuild React.
6. Run Invoke-Migrations.ps1.
7. Start API and worker.
8. Verify health and inspect both logs.

## Rollback

Record the current revision:

    git rev-parse HEAD

Stop both tasks and check out a previously tested tag or commit:

    git checkout <previous-tested-tag-or-commit>
    .\scripts\windows\Install-RecipeControl.ps1

Application code rollback does not automatically downgrade the application database. Only run an Alembic downgrade if that release explicitly documents it and a tested backup exists. Otherwise restore the matching RecipeControl database backup.

Return to the deployment branch when ready:

    git switch <branch-name>

## Backup validation

Database dumps should be:

- created with a consistent transaction
- stored outside the repository
- protected as sensitive production data
- copied off the VM
- restored periodically into an isolated test database

Never restore a RecipeControl dump into opcua_collector.

## Security checklist

- Port 8000 is reachable only from the protected operator network.
- MySQL is not publicly exposed.
- The source account has SELECT only.
- The application account has privileges only on recipecontrol.
- .env ACLs allow only administrators and the RecipeControl service account.
- Scheduled tasks use a non-administrator account.
- ENABLE_LIVE_MODE and VITE_ENABLE_LIVE_MODE remain false.
- Backups and logs follow the site's retention policy.
