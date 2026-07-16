# RecipeControl MVP implementation plan

1. Define safe environment-based settings and document the unresolved collector schema contract.
2. Build a framework-independent minute bucketing and segmentation domain package with exhaustive rule, duration, gap, delta, grouping, and coverage tests.
3. Add SQLAlchemy persistence, Alembic migrations, fixture and MySQL source repositories, transactional analysis workers, REST APIs, and live-session processing.
4. Build the React/TypeScript rule builder, analysis workflow, ECharts timeline, exact-point detail and trends, labels/classifications, duplicate flow, timezone toggle, and live follow controls.
5. Add deterministic fixtures, native local commands, backend/frontend/Playwright tests, run all locally available checks, and document any environment-only limitations.
