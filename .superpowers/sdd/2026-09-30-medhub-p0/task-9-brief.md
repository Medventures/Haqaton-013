## Task 9: End-to-end verification and safe local rollout

**Files:** Modify `scripts/browser_smoke.py`, `README.md`; create `scripts/p0_smoke.py`, `scripts/backup_database.py`, `backend/tests/test_backup_database.py`. Use existing `scripts/recorder_smoke.py`. Application fixes discovered here return to their owning task and receive focused regression tests.

**Interfaces:** Smoke scripts accept environment-configured base URLs/test credentials and use isolated disposable database/storage. `backup_database.py --source PATH --destination PATH` uses SQLite's backup API, refuses existing destination, sets restrictive permissions and verifies `PRAGMA integrity_check` plus table counts without printing clinical values.

- [ ] Add/run backup tests on a synthetic DB: original untouched, backup readable, repeated destination rejected. Test backup failure leaves no misleading “verified” result. Never use shell file copy on a live SQLite WAL database as the backup mechanism.

  Core assertions: `assert integrity_check == "ok"`; `assert backup_counts == source_counts`; `assert destination.stat().st_mode & 0o077 == 0`; `assert second_run.returncode != 0`. First run `.venv/bin/python -m pytest backend/tests/test_backup_database.py -q` red, implement the script, then run green.
- [ ] Run `.venv/bin/python -m pytest backend/tests -q`, Node-22 `npm test`, `npm run build`, and Compose configuration validation without printing expanded secrets. Baseline was 92 backend/9 frontend tests; report actual new totals and warnings, not assumed counts.
- [ ] Run isolated synthetic acceptance: create consultation → upload fixture audio with deterministic test STT → inspect live stages → generate → inspect masked evidence/seek → correct text → old document conflict → regenerate → save/review → approve → preview/download PDF and DOCX. Test-only provider supports precisely declared synthetic corrections; no live API key or user consultation is used.
- [ ] Run six-form export coverage, recorder smoke and 375px mobile overflow check. Inspect a real browser under production CSP and at least one multipage RU/KZ PDF. Verify requests never contain query tokens or third-party document URLs and logs contain no clinical payload.
- [ ] Request whole-change review with the approved spec, this plan, exact file list and fresh tests. Resolve correctness/privacy/data-loss findings before touching the local user database. Record any unavailable PostgreSQL/Docker runtime checks explicitly.
- [ ] Inspect local process ownership and active operation state without reading clinical text. If any user consultation is PROCESSING, defer restart until it finishes; do not kill an active transcription/generation. Stop only the owned local API; preserve settings and frontend work.
- [ ] Create and verify a timestamped restricted backup of the configured SQLite DB using the tested backup script. Apply Alembic head with the current environment, verify revision and aggregate row counts, then restart the API with unchanged settings. Keep the backup; do not automatically restore over new user writes if a later problem appears.
- [ ] Check health and authenticated read-only navigation after restart. Do not generate/approve/export a real consultation as a deployment check. If migration fails, keep service stopped and report recoverable backup and exact failure before any destructive restore.
- [ ] Update README with implemented workflow, canonical evidence limitations, transcript locks, PDF layout difference, backup/rollback procedure, single-instance processing limitation and reproducible test commands. Final handoff reports completed scope, test evidence, backup location and genuine remaining limits.


Read shared constraints/interfaces in .superpowers/sdd/2026-09-30-medhub-p0/context.md.

