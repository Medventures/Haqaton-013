# Task 4 report — transcript revision workflow

Implemented the task-owned revision workflow and restored the Task 2 provider integration. Final verification: **188 passed, 1 warning**, exit 0, including SQLite and PostgreSQL revision tests. No production database, recordings, environment configuration, running service, or Git state was changed.

## Files

- Created `backend/app/transcripts.py`: shared initial/retry transcript persistence, immutable revision snapshots, physician text correction, canonical projection, revision-based freshness guard.
- Modified `backend/app/service.py`: consultation conditional write gate, identity-map refresh, response revision/audio/provenance metadata.
- Modified `backend/app/main.py`: PATCH transcript; shared snapshot persistence for STT/demo; canonical extraction envelope integration; atomic document data/evidence/source persistence; freshness guards for GET/PATCH/approve and existing DOCX export.
- Created `backend/tests/test_transcript_revisions.py`: 23 cases per database (46 total), including concurrent clients, cached ORM state, invalid requests, ownership, retry preservation and legacy exports.
- Modified `backend/tests/test_api.py` and `backend/tests/test_runtime_llm.py`: test doubles accept the actual `on_stage` callback contract and return `ExtractionResult` envelopes.

## RED evidence

Before implementation:

```text
.venv/bin/python -m pytest backend/tests/test_transcript_revisions.py backend/tests/test_api.py -q
18 failed, 16 passed, 1 warning in 13.87s
```

Eleven new revision cases failed: the missing PATCH returned 405 instead of 200/409/422; generation-dependent cases failed at the known string/envelope integration boundary. Seven existing API failures were generation integration regressions (`test_doctor_selected_diagnosis_code_is_validated_audited_and_approved`, `test_template_fields_allow_selected_keys_and_reject_unknown_or_duplicates`, both DOCX tests, `test_full_demo_review_approval_export_and_audit`, `test_restart_releases_unfinished_mock_export`, `test_invalid_state_transition_and_regeneration_protects_review`). The eighth known integration failure was the OpenAI runtime-selection case, subsequently included in the GREEN runs.

Added race/ownership/retry cases before implementation and ran:

```text
.venv/bin/python -m pytest backend/tests/test_transcript_revisions.py -q --tb=short
16 failed, 1 warning in 4.69s
```

The first implementation run yielded 43 passed / 2 failed. Investigation found test-harness causes: the demo provider intentionally rejects edited synthetic fixtures, and sharing one TestClient event loop prevented the async generation/barrier interleave. The regeneration case now supplies a specific corrected-source extraction result with real server evidence validation; competing operations use separate request event loops with shared app/database state.

The first PostgreSQL fixture attempt correctly failed startup because live mode rejects a demo password. The disposable fixture now uses its own synthetic non-demo password for startup, then enables the demo fixture route/provider in that test app only. No authentication implementation was changed.

## GREEN evidence

```text
.venv/bin/python -m pytest backend/tests/test_transcript_revisions.py backend/tests/test_api.py backend/tests/test_runtime_llm.py -q --tb=short
45 passed, 16 skipped, 1 warning in 16.97s

MEDHUB_P0_REVISION_DATABASE_URL='postgresql+psycopg://mephirious@/medhub_p0_task4_20260930?host=/tmp/medhub-p0-postgres.BJdoUn&port=55432' .venv/bin/python -m pytest backend/tests/test_transcript_revisions.py -q --tb=short
32 passed, 1 warning in 14.47s

.venv/bin/python -m pytest backend/tests -q --tb=short
158 passed, 16 skipped, 1 warning in 19.15s
```

After adding final boundary, freshness and legacy tests, full backend verification with PostgreSQL enabled:

```text
MEDHUB_P0_REVISION_DATABASE_URL='postgresql+psycopg://mephirious@/medhub_p0_task4_20260930?host=/tmp/medhub-p0-postgres.BJdoUn&port=55432' .venv/bin/python -m pytest backend/tests -q --tb=short
188 passed, 1 warning in 26.21s
exit 0
```

Only warning: existing Starlette TestClient/httpx deprecation. PostgreSQL runs used escalated access to the controller-created disposable database. The fixture rejects any database name other than `medhub_p0_task4_20260930`, initializes its tables and clears only that dedicated database's test records between cases. Cluster lifecycle remains controller-owned.

## Atomicity and concurrency evidence

`claim_write` first conditionally updates the consultation using its observed `updated_at`, allowed lifecycle statuses, and (for corrections) an EXISTS predicate for the expected transcript revision. This UPDATE obtains SQLite's write lock and PostgreSQL's row lock. It then expires ORM identity-map state and refreshes the consultation with FOR UPDATE, retaining PostgreSQL locking. The procedure never depends on SQLite implementing FOR UPDATE. Child reads/writes occur after this gate.

Concurrent correction tests submit the same expected revision: exactly one succeeds, the other returns 409, the revision advances once, and original `raw_text` remains unchanged. Edit-vs-generate, edit-vs-save and edit-vs-approve tests synchronize both clients after reading the consultation, before either writes; every SQLite and PostgreSQL case returns sorted `[200, 409]`. There were no unhandled database-lock errors or deadlocks. If correction wins, status is TRANSCRIBED and document retrieval is 409.

Generation claims PROCESSING, commits that reservation, expires state and explicitly refreshes the previously loaded transcript before building the canonical source. A dedicated two-session test preloads revision 1 into an `expire_on_commit=False` session, commits revision 2 through another client, then acquires PROCESSING and verifies that the retained ORM instance reads revision 2.

The transaction stores clinical JSON, validated evidence links, source revision, exact masked source text, document version and resulting status together. Correction preserves old document/evidence internally; freshness checks compare revisions rather than trusting status. A test deliberately restores REVIEWED after invalidation and confirms GET/save/approve remain 409.

## Requirement coverage and self-review

- Initial transcripts produce snapshot 1; changes produce an attributed `doctor` snapshot, stable segment IDs/times, fresh normalization/masking and TRANSCRIBED status. Original raw text is assigned only when the transcript row is first created.
- Retrying STT/demo appends a revision with deterministic segment IDs scoped by the revision; a changed retry fixture proves original raw text is preserved while current text changes. Evidence carries the source revision, so identical segment ID spellings across recognition revisions do not make old evidence current.
- No-op correction preserves revision, lifecycle status and document; the consultation write gate still updates its coordination timestamp.
- Unknown IDs, duplicate changes, attempts to edit timestamps, entirely blank final text, and combined text exceeding 500000 characters are rejected without snapshot creation. Approved/sent/processing/created/recording corrections and FAILED without a transcript return 409. Another doctor's read/correction returns 404.
- Regeneration increments document version, clears approval data and requires review again. Current transcript responses project today's canonical masking boundary without mutating historical revision snapshots or claiming a legacy generation's unknown source text.
- Approved legacy documents without transcripts keep null provenance metadata and remain readable/exportable. No transcript is invented.
- Existing provider schema and provenance validation were not weakened. The callback parameter is `on_stage`, matching the actual provider implementation.
- Helpers do not commit partial revision/document transitions; route transactions commit complete transitions. `claim_processing` retains its deliberate committed PROCESSING reservation for long-running operations.

Self-review found no outstanding Task 4 correctness issues. Review should focus on the conditional gate and the exact snapshot/source semantics, not only the happy-path API.

## Task 5 interfaces and limits

- Reuse `claim_write`, `claim_processing`, `save_initial_transcript`, `canonical_source`, and `require_fresh_document` when adding processing/protected-file behavior. Preserve identity-map expiry after gate acquisition; do not load and reuse stale transcript/document instances across competing commits.
- Consultation responses currently expose `processing_runs: []`; Task 5 owns actual stage/run persistence and summaries. The providers already accept `on_stage(stage_key, status, attempt)` but the route intentionally does not persist stages yet.
- `audio_available` currently reports the associated audio row. Protected audio range/file behavior and missing-file handling remain Task 5. PDF endpoints remain Task 5.
- No frontend, production migration, restart, deployment, account/password/configuration changes, or user consultation approval/export occurred.
