# Task5 backend handoff

Task4 integrated and tested canonical extraction, revision snapshots and CAS guards. Read task-4-report.md for exact helper signatures. `claim_write` gates observed updated_at/status plus optional expected revision, expires identity map and locks; `claim_processing` commits PROCESSING reservation. Preserve these guards and refresh ordering. Consultation summaries currently expose empty processing_runs; audio_available currently checks DB row only (replace with real file/expiry availability here).

Task3 exports `render_pdf` from app.forms with same metadata signature as render_docx. Use frozen approved JSON/approver metadata and same authorization gates for both; no editable working copy. Renderer is synchronous; do not block async event loop.

Task2 providers accept on_stage(key, state, attempt); canonical input includes exact final projected masked segments. Do not re-normalize that string (cross-boundary masking intentionally preserves quote whitespace). Existing test provider doubles accept callback but may need real stage events added in task-owned tests.

Important transaction constraint: independent tracker sessions must not write while a SQLite clinical transaction holds the write lock (and inserting a run FK can contend with a PostgreSQL FOR UPDATE on its consultation). Persist stage events around real computation before uncommitted clinical writes; don't commit unrelated clinical changes just to expose telemetry. Terminal lifecycle/run state must not claim failure after a successful saved document.

Other workers own frontend/types/PDF preview; do not edit those files. Stage keys/states/error codes are locked in schemas/context. No .env/live DB/process changes. Dedicated disposable PG cluster available per references.md; ask main if a separate DB is required. Main owns rollout.
