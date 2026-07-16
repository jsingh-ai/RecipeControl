# Production VM deployment

## Scope and security boundary

This deployment runs the historical RecipeControl API, worker, application MySQL database, and nginx frontend on one Linux VM. Only nginx port 80 is published. The application database and API remain on the Compose network, and the live worker is not started.

RecipeControl does not yet implement user authentication. Keep port 80 behind a trusted LAN, VPN, host firewall, reverse proxy with separately managed authentication, or an SSH tunnel. Do not expose it directly to the public internet.

The collector account must have `SELECT` only on `machines`, `tags`, and `tag_samples`. RecipeControl migrations always target the separate writable `recipecontrol` application database.

## Prerequisites

- Linux with current Docker Engine and the Docker Compose plugin
- Git
- Network access from the RecipeControl containers to the collector MySQL server
- A collector MySQL user with `SELECT` only
- At least 4 GB RAM and sufficient disk for exact-minute analysis history and backups

Confirm the tools:

```bash
docker --version
docker compose version
git --version
```

## First deployment

```bash
git clone <repository-url>
cd <repository-folder>
cp .env.production.example .env.production
nano .env.production
docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
docker compose --env-file .env.production -f docker-compose.prod.yml build
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

The one-shot `migrate` service waits for application MySQL, runs `alembic upgrade head`, and must finish successfully before the API and historical worker start. nginx waits for the API health endpoint. The frontend is built with `/api`, so browser traffic stays same-origin and nginx proxies it internally to `api:8000`.

Open `http://<vm-lan-address>/` only from the protected network.

## Production environment

Never commit `.env.production`. At minimum replace:

- `APP_DB_PASSWORD`: URL-safe password for the writable RecipeControl user
- `APP_DB_ROOT_PASSWORD`: strong application-MySQL administrative password
- `SOURCE_DATABASE_URL`: SQLAlchemy URL for the collector read-only account
- `CORS_ORIGINS`: the protected browser origin, such as `http://recipecontrol.internal`

Leave `ENABLE_LIVE_MODE=false`. `HTTP_PORT=80` is the only published port by default.

Passwords embedded in SQLAlchemy URLs must be percent-encoded when they contain `@`, `:`, `/`, `#`, or `%`. Secrets are passed through the uncommitted environment file and must not be placed in Git, screenshots, or support logs.

## Collector MySQL locations

`127.0.0.1` inside a container refers to that container, not the Linux VM. The production Compose file provides `host.docker.internal` through Docker's `host-gateway` mapping to support a collector running directly on the VM.

### MySQL on the VM host

```dotenv
SOURCE_DATABASE_URL=mysql+pymysql://readonly_user:percent_encoded_password@host.docker.internal:3306/opcua_collector
```

MySQL must listen on an address reachable from Docker's bridge, and its grant/firewall must restrict access to the VM/Docker network. Do not grant write privileges.

### MySQL on another network host

```dotenv
SOURCE_DATABASE_URL=mysql+pymysql://readonly_user:percent_encoded_password@10.20.30.40:3306/opcua_collector
```

Allow TCP 3306 only between the RecipeControl VM and that host.

### MySQL in another Docker network

Set the service name and external network:

```dotenv
SOURCE_DATABASE_URL=mysql+pymysql://readonly_user:percent_encoded_password@collector-db:3306/opcua_collector
COLLECTOR_DOCKER_NETWORK=collector_default
```

Then include the opt-in override:

```bash
docker network inspect "$COLLECTOR_DOCKER_NETWORK"
docker compose --env-file .env.production \
  -f docker-compose.prod.yml \
  -f docker-compose.collector-network.yml \
  config --quiet
docker compose --env-file .env.production \
  -f docker-compose.prod.yml \
  -f docker-compose.collector-network.yml \
  up -d --build
```

Do not publish the collector port merely to connect two Docker applications.

## Verify collector grants

Run this while connected as the collector account:

```sql
SELECT CURRENT_USER();
SHOW GRANTS FOR CURRENT_USER;
```

The result should contain `SELECT` only for the collector schema. RecipeControl does not require `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `ALTER`, or `DROP` there.

## Health and logs

```bash
curl --fail http://127.0.0.1/health
curl --fail http://127.0.0.1/api/health
docker compose --env-file .env.production -f docker-compose.prod.yml ps
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 api worker frontend app-db
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f api worker
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm api recipecontrol-source-smoke health
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm api recipecontrol-source-smoke diagnostics
```

The source smoke commands only read the collector. They never open or migrate collector tables.

## Application database backup

Create a protected backup directory and logical backup:

```bash
mkdir -p backups
chmod 700 backups
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T app-db \
  sh -c 'exec mysqldump -urecipecontrol -p"$MYSQL_PASSWORD" --single-transaction --routines --triggers recipecontrol' \
  > "backups/recipecontrol-$(date -u +%Y%m%dT%H%M%SZ).sql"
chmod 600 backups/recipecontrol-*.sql
```

Back up before every application update. Store copies outside the VM according to the site's retention policy. These backups contain RecipeControl definitions, analyses, minute snapshots, and annotations; they do not contain collector tables.

## Restore the application database

Stop writers, restore, then restart:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml stop api worker
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T app-db \
  sh -c 'exec mysql -urecipecontrol -p"$MYSQL_PASSWORD" recipecontrol' \
  < backups/<selected-backup>.sql
docker compose --env-file .env.production -f docker-compose.prod.yml up -d migrate
docker compose --env-file .env.production -f docker-compose.prod.yml up -d api worker frontend
curl --fail http://127.0.0.1/api/health
```

Test restores on an isolated VM before relying on them. Never restore a RecipeControl dump into `opcua_collector`.

## Updating after a Git pull

```bash
cd <repository-folder>
git branch --show-current
git status --short
git pull
docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
docker compose --env-file .env.production -f docker-compose.prod.yml build
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
docker compose --env-file .env.production -f docker-compose.prod.yml ps
curl --fail http://127.0.0.1/api/health
```

Compose reruns the migration gate before replacing API/worker services. Review release notes and take a backup first.

## Safe restart

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml restart api worker frontend
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

Do not start `live-worker`. The historical worker safely reclaims stale jobs using its bounded retry and persistence-lease policy.

## Rollback

1. Record the current revision and take a database backup.
2. Stop API and worker.
3. Check out a previously tested tag or commit.
4. Rebuild and start the prior application.

```bash
git rev-parse HEAD
docker compose --env-file .env.production -f docker-compose.prod.yml stop api worker frontend
git checkout <previous-tested-tag-or-commit>
docker compose --env-file .env.production -f docker-compose.prod.yml build
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
```

Application code rollback does not automatically downgrade the database. Only run an Alembic downgrade if that release explicitly documents it and a tested backup exists. If a schema rollback is unsafe, restore the matching application-database backup instead. Return to the deployment branch with `git switch <branch-name>` when ready.

## Live worker profile

The service is present only for explicit future testing and is not part of normal production startup:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml --profile live config
```

Do not start this profile for the historical MVP. Both backend and frontend live flags remain false by default.
