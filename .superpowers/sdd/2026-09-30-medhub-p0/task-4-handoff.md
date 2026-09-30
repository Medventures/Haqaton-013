# Task 4 integration handoff

Task1 schema/migration reviewed. `TranscriptPatch` validates positive revision, unique IDs, per-text/request bounds; API must validate known IDs and final combined current text (including untouched segments) ≤500000 and nonblank. Stored IDs are deterministic within a revision. Actual original raw_text must remain unchanged.

Task2 provider contract is now canonical input → ExtractionResult. `mask_segments` (app.grounding) also normalizes conservatively, projects whole-text redaction to segments and strips speaker metadata from masked source only. Source.text exactly joins projected segments; do not renormalize it afterwards (cross-boundary masking can leave significant quote whitespace). `validate_evidence(result, source)` resolves server-owned times/revision and validates all quotes. Providers deep-copy source before awaiting transport. Callbacks report `(stage_key, status, attempt)`; Task5 will connect persistence.

The 8 existing integration failures from Task2 are enumerated in task-2-report.md. Existing API monkeypatches still return flat ConsultationData; adapt these to explicit envelope/callback contract. Don't loosen provider validation to make old tests pass.

Original API and user DB have NOT been restarted/migrated. No live processes/.env/storage edits in this task; use disposable tests. PostgreSQL temp cluster is available per references.md, and SQLite/PostgreSQL migration preservation already passed. Controller owns eventual rollout.

Atomicity risk: code uses SQLAlchemy expire_on_commit=False. Reload transcript/document after acquiring the consultation's conditional processing/write gate rather than trusting ORM objects selected before another writer committed. SQLite ignores FOR UPDATE, so test actual competing updates.
