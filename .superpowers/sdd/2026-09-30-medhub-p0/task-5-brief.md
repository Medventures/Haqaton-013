## Task 5: Persist real processing and expose protected PDF/audio

**Files:** Create `backend/app/processing.py`, `backend/tests/test_processing.py`, `backend/tests/test_protected_files.py`; modify `backend/app/main.py`, `backend/app/service.py`, `backend/app/transcripts.py`, `backend/tests/test_api.py`.

**Interfaces:** `ProcessingTracker(session_factory, consultation_id: str, operation: str)` with `start() -> str`, `stage(key: str, state: str, attempt: int = 1) -> None`, `finish() -> None`, `fail(error_code: str) -> None`; `recover_interrupted_runs(session) -> int`. GET audio/PDF and summary contracts are defined above.

- [ ] Add `test_stage_updates_visible_before_request_finishes` with a blocking fake STT/LLM: a second client sees persisted running/completed stages while the action remains pending; completed duration is nonnegative, pending timestamps/durations null, no percentage appears.
- [ ] Add `test_failed_retry_and_restart_preserve_actual_timings`: extraction retry has actual separate attempts, completed stages survive failure, the active stage has a safe error, startup marks interrupted work failed and does not change completed/approved records. Assert no clinical text enters operational logs or error codes.
- [ ] Add endpoint tests: unauthenticated 401, other owner 404, pre-approval PDF 409, missing/expired/demo audio 404, valid audio MIME/no-store, PDF `%PDF-`/no-store. `test_pdf_uses_approved_not_working_snapshot` mutates only a disposable fixture's working copy and checks the approved value alone is rendered; legacy metadata works.

  Core assertions: `assert pending.duration_ms is None`; `assert completed.duration_ms >= 0`; `assert running.status == "running"`; `assert response.headers["cache-control"] == "no-store"`; `assert "UNSAVED_SENTINEL" not in extracted_text`.
- [ ] Run `.venv/bin/python -m pytest backend/tests/test_processing.py backend/tests/test_protected_files.py -q`; confirm failure for absent endpoints/stages.
- [ ] Implement tracker persistence using short independent sessions while long provider calls hold no write transaction. Measure durations with monotonic time, retain UTC boundaries, whitelist safe codes (`UPLOAD_FAILED`, `STT_FAILED`, `NORMALIZATION_FAILED`, `MASKING_FAILED`, `LLM_FAILED`, `VALIDATION_FAILED`, `INTERRUPTED`). Never mask a successful clinical save as failed merely because telemetry cleanup fails; reconcile terminal status atomically where possible.
- [ ] Instrument upload receipt/storage (not browser-network progress), STT, normalization, masking, extraction and validation; wire Task 2 callback and restart recovery. Add the same optional `on_stage` callback to `save_initial_transcript` around actual normalization/masking, retaining transaction ownership in routes. Report model preparation only if a real signal is implemented; otherwise use indeterminate STT with no invented substage.
- [ ] Add protected file routes using registered storage keys and approval snapshot metadata; share DOCX/PDF authorization/loading logic. Audio availability must check the file, not only its DB row, and exclude expired/synthetic recordings; tolerate deletion between availability check and fetch with a safe 404.
- [ ] Return latest run per operation in summaries and revision/audio metadata in transcript responses. Run all backend tests, including endpoint ownership and concurrency tests; review that stage commits cannot commit unrelated pending clinical edits.


Read shared constraints/interfaces in .superpowers/sdd/2026-09-30-medhub-p0/context.md.

