# Task 1 implementation report

Status: implemented; independent review pending.

Changed files:

- `backend/app/models.py`: transcript revision column, protected revision snapshots, document provenance fields, processing-run storage.
- `backend/app/schemas.py`: stored/canonical transcript, edit patch, evidence claim/link and extraction, and processing run/stage contracts. Claimed quote spacing is preserved; model-owned evidence fields are forbidden. Error codes are restricted to the planned safe uppercase set.
- `backend/alembic/versions/0003_trust_workflow.py`: additive SQLite/PostgreSQL migration. Existing segments get deterministic `seg-000001` style IDs; version 1 snapshots preserve existing normalized/masked text, PII, and timestamp. Snapshot actor stays null; source is `demo` only for `demo-fixture`, otherwise `stt`. Documents with a transcript link to revision 1; evidence defaults empty and old source masked text remains null. Processing runs are not fabricated.
- `backend/tests/test_schemas.py`: contract validation, bounds, literal quote whitespace, and safe code regression tests.
- `backend/tests/test_migrations.py`: legacy approved/draft, doctor-edit, audit/account, and transcript migration checks; SQLite downgrade/upgrade round trip; optional disposable PostgreSQL URL.
- `backend/tests/test_api.py`: hardcoded expected Alembic head updated from `0002_consultation_template` to `0003_trust_workflow` after main expanded this file's scope.

RED evidence:

- `.venv/bin/python -m pytest backend/tests/test_schemas.py backend/tests/test_migrations.py -q`: 4 expected failures (missing `EvidenceClaim`, `TranscriptPatch`, `ProcessingRun`, `TranscriptRevisionRow`); 6 passed.
- `.venv/bin/python -m pytest backend/tests/test_schemas.py::test_processing_stage_accepts_safe_codes_and_rejects_free_text -q`: failed because `UPLOAD_FAILED` did not match the old lowercase error-code regex.

GREEN evidence after final code:

- `.venv/bin/python -m pytest backend/tests/test_schemas.py::test_processing_stage_accepts_safe_codes_and_rejects_free_text -q`: 1 passed.
- `.venv/bin/python -m pytest backend/tests/test_schemas.py backend/tests/test_migrations.py -q`: 11 passed.
- `.venv/bin/python -m pytest backend/tests -q`: 97 passed, 1 existing `StarletteDeprecationWarning` from `fastapi.testclient`/`httpx`.
- Disposable PostgreSQL 16: `MEDHUB_P0_TEST_DATABASE_URL='postgresql+psycopg://mephirious@/medhub_p0_task1_20260930?host=/tmp/medhub-p0-postgres.BJdoUn&port=55432' .venv/bin/python -m pytest backend/tests/test_migrations.py::test_p0_migration_preserves_legacy_records -q`: 1 passed. This tested upgrade from `0002` to head, downgrade to `0002`, and upgrade again in a dedicated temporary-cluster database. The user's database was untouched.

Self-review:

- Core preservation assertions compare legacy raw text, original clinical JSON, users, edits, full approval metadata, and timestamps. No migration stage attempts, citations, actor identities, or source payloads are invented.
- Pydantic contracts reject extra fields. `TranscriptPatch` validates positive revision, duplicate IDs, and input size; Task 4 must validate known IDs and final combined current text length/nonblank using the stored unchanged segments. It must assign fresh JSON lists when updating stage records so SQLAlchemy detects changes.
- Legacy transcript `created_at` can be null under the old schema, so snapshot timestamp is nullable rather than invented. New application writes can supply a real timestamp.
- PostgreSQL test URL is a one-use disposable database because the test starts from migration base. A fresh dedicated database is needed for another PostgreSQL run.

Concerns: Task 4 and Task 5 integration still need to wire these contracts into API responses and persistence. The PostgreSQL run verifies migration execution and legacy preservation, not full PostgreSQL runtime behavior.

## Review fix round 1

Reviewer finding: a pending processing stage could carry a timestamp or measured duration. Added a status-aware validator that rejects non-null `started_at`, `finished_at`, or `duration_ms` when status is `pending`; other statuses remain unchanged.

- RED: `.venv/bin/python -m pytest backend/tests/test_schemas.py::test_pending_processing_stage_has_no_measured_timing -q` → 1 failed because `ProcessingStage` accepted a pending start timestamp.
- GREEN: `.venv/bin/python -m pytest backend/tests/test_schemas.py -q` → 10 passed in 0.08s.
