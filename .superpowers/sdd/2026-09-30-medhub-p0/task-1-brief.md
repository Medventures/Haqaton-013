## Task 1: Add compatible persistence and contracts

**Files:** Modify `backend/app/models.py`, `backend/app/schemas.py`, `backend/tests/test_schemas.py`, `backend/tests/test_migrations.py`; create `backend/alembic/versions/0003_trust_workflow.py`.

**Interfaces:** Produce the shared Pydantic contracts above; `TranscriptRow.revision`; `DocumentRow.source_transcript_revision`, `.evidence`, `.source_masked_text`; new `TranscriptRevisionRow` and `ProcessingRunRow` SQLAlchemy models.

- [ ] Write schema tests `test_evidence_rejects_model_owned_times_and_blank_quote` and `test_transcript_patch_bounds`: extra timestamps/revision rejected in claims, blank quotes rejected, literal quote whitespace preserved, negative revision and oversized text rejected.
- [ ] Write `test_p0_migration_preserves_legacy_records`: populate revision 0002 with approved/unapproved consultations, doctor edits, transcripts and an approved document without transcript; upgrade and assert original text/clinical JSON/users/audits unchanged, stable IDs, revision 1, empty evidence, null historical processing and exact approval metadata.

  Core assertions: `assert after.raw_text == before.raw_text`; `assert after.revision == 1`; `assert after.segments[0]["id"] == "seg-000001"`; `assert approved_after == approved_before`; `assert migrated_document.evidence == []`.
- [ ] Run `.venv/bin/python -m pytest backend/tests/test_schemas.py backend/tests/test_migrations.py -q`; verify new tests fail for missing contracts/migration before implementation.
- [ ] Implement additive migration and models. Revision snapshots contain transcript ID, unique `(transcript_id, revision)`, segments, normalized/masked text, PII entities, nullable actor ID, source (`stt`, `demo`, `doctor`) and timestamp. Backfill source from existing demo model marker or STT; do not claim an unknown actor made an edit. Preserve legacy masked text and timestamps verbatim.
- [ ] Persist processing runs in a separate table keyed by run ID, consultation FK, operation/status/start/end and JSON stage list. Assign fresh lists on update so SQLAlchemy persists changes. Document evidence defaults to `[]`; source masked text stays null for legacy generations rather than claiming a historical request payload.
- [ ] Re-run focused tests and the full backend suite. Test downgrade/upgrade on disposable data only. Check PostgreSQL migration execution when a disposable server is available; otherwise record that runtime compatibility remains unverified rather than claiming it passed.
- [ ] Review the changed file list and record test output; hand off the contracts without editing API/provider/frontend files.


Read shared constraints/interfaces in .superpowers/sdd/2026-09-30-medhub-p0/context.md.

