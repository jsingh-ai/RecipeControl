# Architecture

RecipeControl is split into four boundaries:

1. The React/Vite application builds immutable grouped rules, queues analyses, polls persisted status, renders ECharts timelines/trends, and updates one segment label at a time.
2. FastAPI validates product commands and writes only RecipeControl tables through a synchronous SQLAlchemy unit of work. OpenAPI is served at `/docs` and `/openapi.json`.
3. Historical and live worker processes read persisted work, fetch bounded source rows through `SourceDataRepository`, call the same pure engine, and transactionally store compressed output.
4. Source adapters expose metadata/samples without write methods. The fixture adapter is deterministic. All unresolved live MySQL identifiers are isolated in `source/mysql.py`.

The application database and source database have separate URLs and engines. Alembic targets only the application engine. The API never returns connection strings, SQL exceptions, or source values outside requested metadata/trend/evaluation responses.

Historical job claiming uses an atomic conditional `QUEUED` to `RUNNING` update so competing workers cannot claim the same row. Output replacement is idempotent and transactional. Analysis completion occurs in that same commit.

The browser uses TanStack Query for server state, React Hook Form plus Zod for rule validation, ECharts custom series for compressed Gantt lanes, and `Intl.DateTimeFormat` with `America/Chicago` for Central presentation. UTC remains canonical.

