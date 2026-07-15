# Application data model

`rc_machine` mirrors stable source machine keys. `rc_rule_set` is a logical machine-specific definition, while `rc_rule_version`, `rc_rule_group`, and `rc_rule_condition` store an immutable saved expression. A newly created version contains no groups, conditions, display settings, or classifications.

`rc_analysis` records the exact machine, version, inclusive selected range, calculated exclusive end, mode, reproducibility metadata, and state. `rc_analysis_job` is the persisted historical queue. Duplicate lookups use a composite index across machine, version, range, and mode.

`rc_segment`, `rc_condition_interval`, and `rc_boundary_event` contain compressed engine output. `rc_analysis_minute` stores one compact JSON snapshot for each visible minute and links it to the owning segment; `(analysis_id, minute_utc)` and `segment_id` are indexed. Timeline loads remain compressed while hover/detail retrieves one exact minute on demand. Segment boundaries have no update endpoint. Segment labels allow Good, Bad, Unsure, or NULL/Unlabeled. Training eligibility is computed only for Good/Bad segments that are neither Data Gap nor Insufficient History.

`rc_classification` belongs to an exact saved version. Retirement is soft; segments retain both the foreign key and name snapshot. `rc_label_history` audits every label/classification/note save. Notes are limited to 4,000 characters by default.

`rc_live_session` owns an active live analysis and heartbeat/finalization state. `rc_processing_checkpoint` is available for durable incremental state extensions. All timestamps are stored as UTC and all intervals are half-open.
