# Task 9 independent backup subtask report

## Independent review fix — pathname substitution

The independent reviewer correctly found a blocking race in the original implementation: SQLite reopened the public destination after its exclusive file descriptor had closed, so replacing that pathname with a symlink could overwrite another database. The original inode-check-then-unlink cleanup also exposed a replacement race. The earlier self-review conclusion below is superseded by this finding and fix.

Before edits, both task-owned files were copied to `/tmp/medhub-backup-before-fix.iqBJeV/` for isolated review. New regression tests reproduced the overwrite and a false verified result when replacing the destination during integrity verification: **2 failed, 8 passed**. The implementation now creates and verifies SQLite output entirely within a mode-0700 private staging directory, then publishes the verified mode-0600 inode via atomic `os.link` (no overwrite). It never opens or unlinks the public destination. A final inode/type/mode check occurs after staging cleanup, so replacements during cleanup also cannot receive a verified result. Failures preserve unrelated replacement paths and targets.

An intermediate run caught that cleanup itself can trigger a replacement after an earlier identity check (**1 failed, 10 passed**). Moving the final published identity check after private staging cleanup closed that window. Final focused run: `.venv/bin/python -m pytest backend/tests/test_backup_database.py -q --tb=short` → **11 passed in 0.57s**. Added coverage includes destination substitution after fd close, substitution during verification, and substitution after publication; targets remain byte-for-byte untouched. All fixtures remain synthetic. Real backup/deployment remains controller-owned.

Full backend suite after this fix and before Task 5 implementation: **176 passed, 23 skipped, 1 existing deprecation warning in 20.60s**, exit 0.

Implemented only the backup script and its synthetic tests. **8 backup tests pass**; the full backend suite at handoff reports **173 passed, 23 skipped, 1 warning**. No real backup, migration, restart, production data access, README/smoke changes or other task-owned production changes occurred.

## Files

- `scripts/backup_database.py`
- `backend/tests/test_backup_database.py`

## Behavior

`python scripts/backup_database.py --source PATH --destination PATH` opens the source via SQLite `mode=ro`, pins one read transaction, records table counts, and calls SQLite's backup API. This includes committed WAL content and keeps source counts consistent with the copied snapshot even when another writer commits during backup.

The destination is created atomically with `O_CREAT | O_EXCL` and permissions `0600`; an existing file, the source itself, and a symlink destination are rejected without overwriting anything. The resulting backup uses DELETE journal mode so it is independently readable as one file. Verification runs `PRAGMA integrity_check` and compares every table count with the pinned source snapshot, including correctly quoted unusual table identifiers.

Success emits only JSON verification metadata (`verified`, `integrity_check`, `table_counts`). Failure exits nonzero with a fixed safe error and no success JSON or exception details. An incomplete file created by this attempt is removed after connections close; inode checking prevents removal of an existing or replaced destination. A missing source is never created.

## TDD / verification evidence

Initial negative tests accepted any failure, which could pass with a missing script. Those assertions were tightened to require the script's safe failure contract before implementation.

```text
.venv/bin/python -m pytest backend/tests/test_backup_database.py -q --tb=short
6 failed in 0.20s
```

All six failed because the script did not yet exist. After implementation:

```text
.venv/bin/python -m pytest backend/tests/test_backup_database.py -q --tb=short
6 passed in 0.31s
```

Added explicit snapshot-concurrency and count-mismatch coverage, and strengthened the post-copy integrity-failure case to exercise the CLI's no-clinical-error-output behavior:

```text
.venv/bin/python -m pytest backend/tests/test_backup_database.py -q --tb=short
8 passed in 0.35s

.venv/bin/python -m pytest backend/tests -q --tb=short
173 passed, 23 skipped, 1 warning in 21.72s
exit 0
```

Skipped tests are Task 4's PostgreSQL parameterizations because the optional disposable PostgreSQL URL was not supplied for this independent SQLite-only subtask. The warning is the existing Starlette TestClient/httpx deprecation.

## Self-review / scope boundary

Synthetic WAL tests verify that the original main-database bytes and clinical values are unchanged, backup contents are readable and complete, mode is exactly 0600, and no synthetic private value reaches stdout/stderr. The concurrent-write test commits a second source row after counting but before copying: the source ends with two rows while the verified backup consistently contains the original one-row snapshot. Integrity failure and count mismatch both remove the newly created incomplete destination and produce no verified result.

No outstanding correctness findings within this subtask. The script intentionally does not restore, migrate, restart, delete old backups, or create destination parent directories. The controller retains all later rollout authority and should keep a successful backup at its explicitly chosen destination.
