# Source collector schema

## Discovery status

No `db.py`, SQL, application files, or reachable source database configuration existed in the repository at discovery time (2026-07-14). Consequently, the live collector's database name, MySQL version, tables, relationships, primary key, value representation, timestamp type, and indexes cannot be truthfully mapped yet. RecipeControl does **not** invent these column names.

All unresolved mappings are confined to `backend/recipecontrol/source/mysql.py`. That adapter fails closed until its explicitly named mapping environment variables are supplied. The rest of the application depends only on the `SourceDataRepository` protocol in `backend/recipecontrol/source/base.py` and runs with the deterministic fixture adapter.

## Required source adapter contract

The live adapter must provide:

- machines: stable source key and display name;
- tags for a machine: stable tag key, display name, source data type, and optional units;
- samples for selected tag keys in a bounded half-open UTC interval;
- for each sample: tag key, `sampled_at_utc`, typed/raw value, and a deterministic row tie-breaker.

`sampled_at_utc` is authoritative UTC. A naive MySQL datetime is attached to UTC on ingestion. RecipeControl never forward-fills values. Rows are bucketed by UTC minute; greatest timestamp wins and the greatest deterministic source key breaks timestamp ties. SQL NULL is retained as missing.

## Value normalization

- Numeric values are parsed from lossless text into Python `Decimal`.
- Text and alarm codes use direct typed comparison. A numeric alarm-code column should be mapped as numeric; a character column as text.
- Boolean source mappings must identify the actual true/false encodings. The default adapter accepts database booleans and the canonical forms `true`, `false`, `1`, and `0`, case-insensitively.
- SQL NULL is a Data Gap and is never coerced.

## Query strategy and safety

The source connection is configured independently with `SOURCE_DATABASE_URL` and is used only for parameterized `SELECT` and metadata/readiness operations. RecipeControl never migrates or writes the source database. Queries select only requested tags and bounded UTC ranges, including the engine-computed preload horizon. Sample reads are streamed/chunked by the adapter.

The precise table/column mapping is supplied by environment variables documented in `.env.example`. Identifiers are allow-listed before SQL construction; values remain bound parameters.

## Index review and recommendation

Live index metadata was unavailable. After mapping the real schema, inspect `SHOW INDEX` read-only. If an equivalent composite index is absent, a source-database administrator may consider the following separately; RecipeControl never applies it:

```sql
CREATE INDEX ix_tag_samples_tag_time
    ON tag_samples (tag_id, sampled_at_utc, id);
```

Replace names with discovered identifiers. The ordering supports bounded reads for selected tags plus deterministic latest-row selection. Validate write overhead and existing overlapping indexes before applying.

## Fixture schema

The fixture repository provides machines and tags for temperature, pressure, speed, alarm code, and motor-running, including duplicate-minute rows, tied timestamps, NULLs, missing rows, delta changes, and overlapping condition activity. It is a development/test source only and is not asserted to match the absent collector schema.
