## Task 4: Implement atomic transcript correction and stale-document guards

**Files:** Create `backend/app/transcripts.py`, `backend/tests/test_transcript_revisions.py`; modify `backend/app/main.py`, `backend/app/service.py`, `backend/tests/test_api.py`, `backend/tests/test_runtime_llm.py`.

**Interfaces:** `save_initial_transcript(session, consultation, transcript, *, actor_id: str | None, source: str, stt_model: str) -> TranscriptRow`; `edit_transcript(session, consultation, patch: TranscriptPatch, *, actor_id: str) -> TranscriptRow`; `require_fresh_document(document: DocumentRow, transcript: TranscriptRow | None) -> None`. Service helpers do not commit partial revision/document transitions. Routes own transactions.

- [ ] Write `test_edit_preserves_original_and_invalidates_document`: revision 1 → 2, original `raw_text` unchanged, IDs/timestamps unchanged, second snapshot attributed to doctor, fresh PII masking, status TRANSCRIBED, old document/evidence retained internally, GET/PATCH/approve of stale document return 409. Regeneration increments document version and requires review again.
- [ ] Write `test_noop_edit_does_not_invalidate`, `test_approved_and_processing_transcripts_are_locked`, and malformed/unknown/duplicate segment tests. Assert no-op keeps revision/status/document; no partial snapshots survive failed requests; read/update requests from another doctor return 404.
- [ ] Write `test_competing_transcript_edits_have_one_winner` and `test_edit_races_with_generation_save_and_approval`: interleave two DB sessions/clients at synchronization barriers; only one conflicting write succeeds, stale versions receive 409, no deadlock or unhandled database-lock response, no stale approval.

  Core assertions: `assert sorted(response_codes) == [200, 409]`; `assert current.revision == original.revision + 1`; `assert current.raw_text == original.raw_text`; `assert stale_get.status_code == stale_save.status_code == stale_approve.status_code == 409`.
- [ ] Run `.venv/bin/python -m pytest backend/tests/test_transcript_revisions.py backend/tests/test_api.py -q`; confirm failing new tests.
- [ ] Implement a consultation-level conditional write gate plus expected transcript revision inside one transaction, retaining row locks on PostgreSQL. Do not rely on SQLite `FOR UPDATE`. Reject edits outside TRANSCRIBED/AI_GENERATED/REVIEWED/FAILED and reject FAILED without a transcript. Detect no-op before invalidation.
- [ ] Save initial and corrected snapshots through the shared normalization/masking boundary. A subsequent STT retry must not overwrite the original ASR text or reset revision to 1: if an existing transcript is legitimately replaced, append an STT revision with segment identities scoped to that revision; never reuse old evidence as current. Keep physician PATCH text-only.
- [ ] Update generation to consume the current canonical source and save data, validated server evidence, source revision and exact `source_masked_text` atomically. Legacy snapshots remain unchanged; current transcript responses may compute the canonical projection from stored segments so privacy preview matches today's extraction boundary. No claim is made about a legacy generation's unknown input.
- [ ] Implement freshness guards for document GET/save/approve, preserving approved legacy exports with absent optional metadata. Refresh state after claiming PROCESSING to avoid using a pre-lock stale transcript. Adapt API/runtime test doubles to Task 2's extraction envelope and callback signature. Run focused and full backend tests; review races and stale reads before handoff.


Read shared constraints/interfaces in .superpowers/sdd/2026-09-30-medhub-p0/context.md.

