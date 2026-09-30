# Task 5 — processing telemetry and protected files

Task-owned implementation is frozen for independent review. Full dual-database backend run: **219 passed, 2 failed, 1 existing warning**; both failures are the concurrent Task 9 smoke-harness tests whose implementation file did not yet exist. The controller explicitly authorized reporting this named parallel-work gap rather than waiting. All Task 5 tests and existing revision/concurrency tests passed.

## Files

- Created `backend/app/processing.py`.
- Created `backend/tests/test_processing.py` and `backend/tests/test_protected_files.py`.
- Modified `backend/app/main.py`, `backend/app/service.py`, `backend/app/transcripts.py`.
- No frontend, environment, production database, process, storage recording, README or smoke-harness changes in this task. `backend/tests/test_api.py` required no additional Task 5 modifications: Task 4 already adapted its provider callback signatures.

## Interfaces and behavior

`ProcessingTracker(session_factory, consultation_id, operation)` provides `start()`, `stage(key, state, attempt=1)`, `finish()` and `fail(error_code)`. An optional keyword `session` on terminal methods lets routes update run state in the same transaction as the final clinical save; when omitted, those methods retain independent-session behavior. `latest_attempt` and `failure_code` support provider retry handling without storing exception contents. `recover_interrupted_runs(session)` changes unfinished runs and their active stages without committing the caller's transaction.

Stage keys and error codes are strictly whitelisted. Pending stages have null timestamps/durations. Running stages use UTC start times, and completed/failed attempted stages store monotonic measured milliseconds. Provider retries append actual attempt records. Restart recovery preserves completed durations and marks active stages INTERRUPTED with unknown duration, since a previous process's monotonic clock cannot be reconstructed. Completed and approved consultation records are not changed by recovery.

The upload stage measures server-side receipt/read/storage, not browser-network percentage. STT, normalization and masking have actual stage boundaries. `save_initial_transcript` now accepts `on_stage` and emits normalization/masking around the corresponding computation, before it flushes clinical changes. Generation consumes the exact canonical source, forwards provider callbacks, and keeps output validation running through the server's evidence/template checks. No invented model-loading stage, elapsed percentage or historical timing was added.

GET `/api/v1/consultations/{id}/audio` authenticates ownership, checks the registered audio row, file existence and retention cutoff, and excludes synthetic transcript audio. It returns the stored MIME and `Cache-Control: no-store`. Files disappearing between availability check and open return a safe 404. The final open uses `O_NOFOLLOW` and verifies a regular file, so a replaced symlink cannot disclose a different file.

GET `/api/v1/consultations/{id}/document.pdf` shares approved-document authorization, freshness, schema validation and frozen approval metadata with DOCX. Both synchronous export routes render `doctor_approved_data`, never the working draft, return no-store and preserve legacy nullable provenance. Rendering runs as a synchronous FastAPI endpoint in its thread pool rather than blocking an async request loop.

Consultation summaries return the latest run per operation, at most three, in upload/transcribe/generate order. Transcript and consultation audio flags use actual file/retention/synthetic checks rather than existence of a database row alone.

## Transaction review

Task 4's consultation CAS and expected revision gates are preserved. Upload now claims the same committed PROCESSING reservation as STT/generation before it begins any independently persisted stage. Tracker creation therefore does not wait behind an uncommitted PostgreSQL FOR UPDATE/FK conflict. Provider work and stage callbacks run before any clinical write transaction is held. Normalization/masking callbacks finish before `_snapshot` flushes the transcript.

After all computations/stages, the clinical result and terminal run state commit together. Failure first rolls back pending clinical writes, then records run error and consultation FAILED together. No independent telemetry cleanup is performed after a successful clinical commit. Response construction is outside the processing exception boundary, so later serialization/response work cannot reclassify a saved document as a processing failure.

Tracker writes use their own short-lived sessions and cannot accidentally commit another session's pending clinical edit. A two-session regression specifically verifies that an unrelated unsaved patient-ID edit remains uncommitted while stage updates become visible.

## RED/GREEN evidence

Initial test setup exposed a missing imported `sqlite_client` fixture dependency; that harness issue was corrected before establishing RED.

```text
.venv/bin/python -m pytest backend/tests/test_processing.py backend/tests/test_protected_files.py -q --tb=short
7 failed, 7 skipped, 1 warning in 13.81s
```

RED failures were missing persisted stages/callbacks, absent tracker module and missing audio/PDF GET routes (405/404 rather than the required authenticated responses).

```text
.venv/bin/python -m pytest backend/tests/test_processing.py backend/tests/test_protected_files.py backend/tests/test_api.py -q --tb=short
30 passed, 7 skipped, 1 warning in 12.52s

MEDHUB_P0_REVISION_DATABASE_URL='postgresql+psycopg://mephirious@/medhub_p0_task4_20260930?host=/tmp/medhub-p0-postgres.BJdoUn&port=55432' .venv/bin/python -m pytest backend/tests/test_processing.py backend/tests/test_protected_files.py backend/tests/test_transcript_revisions.py -q --tb=short
60 passed, 1 warning in 23.28s
```

Added final startup-preservation/latest-run coverage and a symlink-replacement regression. That file regression first returned 200 with substituted bytes (RED: **1 failed, 1 skipped**); the protected open was then changed to reject symlinks.

```text
MEDHUB_P0_REVISION_DATABASE_URL='postgresql+psycopg://mephirious@/medhub_p0_task4_20260930?host=/tmp/medhub-p0-postgres.BJdoUn&port=55432' .venv/bin/python -m pytest backend/tests -q --tb=short
2 failed, 219 passed, 1 warning in 36.43s
```

Exactly two concurrent Task 9 failures:

- `backend/tests/test_p0_smoke_harness.py::test_synthetic_stt_accepts_only_the_declared_audio`
- `backend/tests/test_p0_smoke_harness.py::test_synthetic_llm_accepts_only_declared_revisions_and_yields_grounded_evidence`

Both raised `FileNotFoundError` for `/home/mephirious/Projects/medhub/scripts/p0_smoke.py`, which its separate worker had not yet created. They were reported promptly to the controller and left untouched. The sole warning is the existing Starlette TestClient/httpx deprecation.

The final run includes all **20 Task 5 SQLite/PostgreSQL cases**, plus the Task 4 two-client correction/generation/save/approval races. No database-lock errors or deadlocks occurred. PostgreSQL access was limited to the controller-created disposable database already used by Task 4 fixtures; no production database or process was accessed.

## Behavioral evidence and self-review

- A second client sees upload completion and a running STT stage before the blocked transcription request returns. Normalization/masking remain pending with entirely null timing until actually run.
- A blocked second LLM attempt exposes completed attempt-1 extraction, failed attempt-1 validation and running attempt-2 extraction. Failure preserves measured completed times and records only `LLM_FAILED`, never the synthetic private exception string; response and captured logs likewise omit it.
- Restart via actual application lifespan recovers a running operation, preserves completed run stages and leaves an APPROVED consultation unchanged.
- Successful generation's terminal tracker update is explicitly required by test to use the clinical session.
- Auth, other-owner 404, pre-approval PDF 409, unavailable/expired/synthetic audio 404, approved-snapshot PDF content, no-store, and symlink/deletion races are exercised on both databases.
- Export test mutates only a disposable working JSON copy with `UNSAVED_SENTINEL`; extracted PDF text contains the approved cough text and never that sentinel.

No outstanding Task 5 correctness issue was found in self-review. Whole-suite green after the parallel smoke harness lands remains a rollout gate. App polling, frontend rendering and real production-CSP browser acceptance remain other tasks' responsibilities. The existing single-process recovery model is unchanged.
