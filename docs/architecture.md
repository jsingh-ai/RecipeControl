# Architecture

RecipeControl is split into four boundaries:

1. The React/Vite application builds immutable grouped rules, queues analyses, polls persisted status, renders ECharts timelines/trends, and updates one segment label at a time.
2. FastAPI validates product commands and writes only RecipeControl tables through a synchronous SQLAlchemy unit of work. OpenAPI is served at `/docs` and `/openapi.json`.
3. Historical and live worker processes read persisted work, fetch bounded source rows through `SourceDataRepository`, call the same pure engine, and transactionally store compressed output.
4. Source adapters expose metadata/samples without write methods. The fixture adapter is deterministic. The MySQL adapter in `source/mysql.py` implements the exact `opcua_collector` schema and typed dual-column decoding.

The application database and source database have separate URLs and engines. Alembic targets only the application engine. The API never returns connection strings, SQL exceptions, or source values outside requested metadata/trend/evaluation responses.

Each API or worker process owns one cached source repository and SQLAlchemy pool.
Forked children clear inherited cache state, and API/worker shutdown disposes the
process-local source engine. Machine synchronization disables missing source machines
locally without deleting immutable definitions or historical analyses.

Historical job claiming uses an atomic conditional `QUEUED` to `RUNNING` update so competing workers cannot claim the same row. Workers heartbeat while streamed samples are consumed. Stale jobs are reclaimed until a bounded retry limit, then fail with a sanitized UI message. Output replacement, including batched exact-minute rows, is idempotent and transactional. Analysis completion occurs in that same commit.

The browser uses TanStack Query for server state, React Hook Form plus Zod for rule validation, ECharts custom series for compressed Gantt lanes, and `Intl.DateTimeFormat` with `America/Chicago` for Central presentation. UTC remains canonical.
