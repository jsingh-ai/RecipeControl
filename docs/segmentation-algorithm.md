# Segmentation algorithm

The pure engine accepts an immutable `RuleDefinition`, source samples, a UTC start minute, and an inclusive UTC end minute. It calculates `end_exclusive = end + 1 minute` and a preload of the maximum condition duration plus delta window plus one safety bucket.

It selects the greatest timestamp per tag/minute, then the greatest deterministic tie-breaker. Values are normalized to Decimal, text, or Boolean; no values are forward-filled. A complete grid marks any missing/NULL required variable as Data Gap. When delta rules exist, valid data following a gap remains Insufficient History until the largest continuous lookback is available.

Raw predicates implement strict lower/upper limits, inclusive acceptable ranges, exact typed equality, and absolute deltas against the exact lookback minute. True runs are activation-duration filtered. Confirmed runs are backdated to their first true minute; unconfirmed terminal runs remain pending and never split the primary lane. False recovery is immediate.

Confirmed conditions satisfy one-level uniform AND/OR groups and a root AND/OR. A satisfied AND contributes all members; a satisfied OR contributes every active member. Primary identity is one of `DATA_GAP`, `INSUFFICIENT_HISTORY`, `NORMAL`, or `BREAK:<sorted IDs>`. A changing contributor set creates a boundary even while the root remains true.

Adjacent equal identities and condition states are compressed. Boundary events retain values, raw/confirmed states, trigger/confirmation details, group/root results, missing variables, delta references, and a deterministic explanation. Assertions require ordered, gapless, non-overlapping coverage of the exact visible half-open interval.

