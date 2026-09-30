# Task 9 isolated acceptance report — 2026-09-30

Status: synthetic acceptance passed against Task 7 build 1; one final rerun after Task 7's newly identified revision-keyed transcript-query fix/build 2 is pending. Live rollout is **not** performed by this worker.

## Scope and files

Owned changes: `scripts/p0_smoke.py` (new), `scripts/browser_smoke.py`, `backend/tests/test_p0_smoke_harness.py` (new focused tests), `README.md`. The existing `scripts/recorder_smoke.py` is invoked unmodified. Backup implementation/tests belong to another worker and were reviewed separately. No application product files, configured database, `.env`, real recording, existing API process, or user consultation were changed by this acceptance worker.

## RED → GREEN evidence

- The first two synthetic-provider tests failed because `scripts/p0_smoke.py` did not exist; after implementing the declared WAV/revision-only STT/LLM, both passed.
- The recorder-integration test failed with missing `BROWSER_SCRIPTS`; after wiring both `browser_smoke.py` and `recorder_smoke.py` into the isolated run, 3 focused tests passed.
- The configuration-isolation test failed with missing `isolated_settings_environment`; after clearing/restoring all `Settings` environment/secret-file keys around the backend app import and removing them from browser subprocess environments, 4 focused tests passed.
- Initial integration found a harness-only Nginx client-body temp-directory permission error; moving that directory into the private synthetic output fixed large transcript PATCH requests. Browser selector ambiguity and Playwright's premature zero-byte `response.body()` capture were also harness-only; the final byte identity check hashes a clone of the exact completed browser `fetch` response against the downloaded Blob.

Latest focused command: `.venv/bin/python -m pytest backend/tests/test_p0_smoke_harness.py -q` → **4 passed in 2.15s**. Parent independently ran the full backend suite, **221 passed, 1 baseline warning**, in 42.58s. Task 7 owner ran frontend **61 passed** and rebuilt `dist` for this acceptance; its build 2 fix is in progress.

Latest integrated command: `.venv/bin/python scripts/p0_smoke.py` → **passed**, artifact directory `/tmp/medhub-p0-acceptance-5lqr30rs` (private temporary SQLite/storage; no configured DB or OpenAI key). This used the Task 7 build 1 frontend under the actual `deploy/nginx.conf` server block and production CSP, with local API proxy and `.mjs` worker MIME mapping, on disposable loopback ports. No Docker daemon was required. Nginx access logging was disabled; its error log was 0 bytes.

Final checks:

- All six forms: create, upload declared synthetic WAV, observe `PROCESSING`, transcribe, masked text, generate, save, approve, PDF `%PDF` and valid DOCX. Therapist flow additionally checks stale transcript edit conflict (409), invalidated document and regenerated revision. `pdfinfo` confirms a multipage RU/KZ PDF.
- Chromium: login/create/upload; visible measured processing; masked transcript and privacy panel; grounded quote seeks local audio to 00:04; edit invalidates the draft, regenerate, save/review/approve, and DOCX contains the saved synthetic conclusion.
- PDF.js 6 local `.mjs` worker responds as JavaScript under Nginx; first and next canvases paint different pages. Download SHA-256 and size match the original preview fetch Blob exactly. Preview closes/reopens, survives consultation switch, and fits a 375px viewport without horizontal overflow. No third-party request, query-token/secret URL, or JavaScript page error was observed.
- Fake microphone recorder: two MediaRecorder uploads returned 200, including retry, and enabled transcription; no real microphone or clinical audio was used.

Visually inspected safe, genuine synthetic browser captures: `synthetic-login.png`, `synthetic-workspace.png` (fully created, no modal), `synthetic-processing.png`, `synthetic-transcript.png`, `synthetic-privacy.png` (full current-versus-sent masked text), `synthetic-evidence.png`, `synthetic-doctor-review.png` (readable 1600×900 populated fields), `synthetic-pdf-preview.png`, and `browser-mobile-preview.png`. Paths are under the final artifact directory above. The presentation worker received these paths as synthetic-only material.

## Documentation and limits

README now documents the implemented six-form/revision/evidence/privacy/approval/PDF flow, regex masking limitations, provenance versus medical correctness, separately laid-out PDF, single-instance interrupted-run recovery, restricted SQLite backup/manual rollback safeguards, and reproducible synthetic commands. The newly requested branded PDF/QR, sparse empty print fields, and disease-protocol checks are later design scope, **not** covered or claimed here. Actual local user-database backup/migration/restart, Docker runtime, PostgreSQL runtime and post-restart read-only navigation remain controller-owned pending rollout; no live change is implied by this synthetic result.
