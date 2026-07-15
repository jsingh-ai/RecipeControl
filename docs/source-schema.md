# Authoritative opcua_collector source mapping

RecipeControl reads three collector-owned tables and never creates, alters, deletes from, or inserts into them: `machines`, `tags`, and `tag_samples`. Collector `poll_runs` and `machine_poll_runs` are also outside the application schema. A separate MySQL engine is created from `SOURCE_DATABASE_URL`; its account must be restricted to `SELECT`. The connection session is set to `+00:00`, and naive `DATETIME(6)` values are attached to UTC.

Verify the configured source account directly as that account:

```sql
SHOW GRANTS FOR CURRENT_USER;
```

The result should grant `SELECT` only on the collector schema. RecipeControl does
not require `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `ALTER`, or `DROP` there.

`machines` provides `id`, `machine_name`, and `enabled`. `tags` provides `id`, `machine_id`, `node_id`, `opc_path`, nullable `display_name`, nullable `browse_name`, nullable `data_type`, and `enabled`. `tag_samples` provides the authoritative `sampled_at_utc`, numeric/text storage, quality/status/error fields, and deterministic `id`.

## Exact reads

Enabled machines:

```sql
SELECT id, machine_name
FROM machines
WHERE enabled = 1
ORDER BY machine_name
```

Tag search selects enabled tags for one bound machine ID, searches lower-cased display name, browse name, node ID, and OPC path, and binds query, limit, and offset. Display name uses the first nonblank value from `display_name`, `browse_name`, and `node_id`.

Sample reads are machine-isolated and half-open:

```sql
SELECT ts.id, ts.tag_id, ts.machine_id, ts.sampled_at_utc,
       ts.value_numeric, ts.value_text, ts.quality,
       ts.status_code, ts.error_text
FROM tag_samples ts
WHERE ts.machine_id = :machine_id
  AND ts.tag_id IN (:tag_ids)
  AND ts.sampled_at_utc >= :start_utc
  AND ts.sampled_at_utc < :end_utc
ORDER BY ts.sampled_at_utc, ts.tag_id, ts.id
```

The `IN` list uses SQLAlchemy expanding bound parameters. The June 11 19:50 through June 23 14:20 inclusive selection therefore reads through `2026-06-23 14:21:00 UTC` exclusive.

## Data kinds and decoding

Mapping is case-insensitive and strips common namespaces/prefixes. `Byte`, `SByte`, signed/unsigned integer families, `Float`, `Float32`, `Float64`, `Double`, `Decimal`, `Number`, `Integer`, and `UInteger` map to `numeric`; forms such as `VariantType.Double` and `Opc.Ua.Double` therefore normalize correctly. `Boolean` and `System.Boolean` map to `boolean`. `String`, `Char`, `DateTime`, `Guid`, `LocalizedText`, and other clearly textual declarations remain text even if numeric storage is populated. For an unknown declaration, observed numeric storage is a numeric fallback and canonical Boolean text is a Boolean fallback. Arbitrary text is never parsed as numeric.

Run `.venv/bin/recipecontrol-source-smoke diagnostics` to report enabled machine/tag
counts, distinct raw type values with normalized kinds, and per-machine sample bounds.
The report contains no connection URL, username, password, or endpoint secret.

- Numeric snapshots use only `value_numeric`; arbitrary `value_text` is never parsed as a number.
- Text/alarm-text snapshots use `value_text`; the empty string is valid.
- Boolean snapshots accept numeric 0/1 or canonical case-insensitive text `true`, `false`, `0`, or `1`.
- An unusable typed value is `NULL`/missing. Quality alone never changes a present typed value into Data Gap.

The raw OPC type and normalized data kind are both snapshotted into a draft during save and resolved again immediately before lock. Locked snapshots are immutable if the collector tag is later renamed or retyped.

## Safety and indexing

`APP_DATABASE_URL` must use a different writable credential. Configuration rejects the same username on the same MySQL host/port as `SOURCE_DATABASE_URL`. Alembic contains operations only for `rc_*` tables.

If absent, a collector administrator may separately review an index on `(machine_id, tag_id, sampled_at_utc, id)`. RecipeControl never applies collector indexes or grants.
