# Live shadow mode

Live sessions are read-only with respect to the collector and reuse the historical segmentation engine. The live worker finalizes through `current UTC minute - finalization lag`; the default lag is two minutes. Finalized minutes are processed in order, the newest segment is marked active, and the UI polls for timeline and heartbeat updates. Pausing auto-follow affects only viewport behavior.

Duration confirmation is reflected by backdating within the engine's bounded duration/delta horizon. A stale indicator appears when a heartbeat is missing or older than three minutes. Latest observed values and their source timestamps use a separate endpoint and never imply finalization.

Reliable very-late-row detection requires a collector ingestion/update sequence that was unavailable because the live source schema was absent. The configured delay absorbs ordinary lateness. The live worker therefore does not claim that a finalized bucket is immutable based on an undiscovered column. `POST /api/live-sessions/{id}/repair` explicitly rewinds the checkpoint and requests the same bounded duration/delta-horizon merge. After the real schema is mapped, ingestion-sequence detection can call that repair automatically. Historical analyses change only through an explicitly created analysis.
