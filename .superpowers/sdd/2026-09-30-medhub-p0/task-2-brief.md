## Task 2: Build one canonical masking and evidence boundary

**Files:** Create `backend/app/grounding.py`, `backend/tests/test_grounding.py`; modify `backend/app/pii.py`, `backend/app/providers/base.py`, `backend/app/providers/llm.py`, `backend/app/providers/demo.py`, `backend/tests/test_pii.py`, `backend/tests/test_providers.py`.

**Interfaces:** `normalize_segments(segments: list[StoredTranscriptSegment]) -> list[StoredTranscriptSegment]`; `mask_segments(segments: list[StoredTranscriptSegment], *, revision: int) -> CanonicalTranscript`; `validate_evidence(result: ExtractionResult, source: CanonicalTranscript) -> list[EvidenceLink]`. Provider method becomes `extract_consultation(source: CanonicalTranscript, *, template_fields: list[dict] | None = None, on_stage: Callable[[str, str, int], None] | None = None) -> ExtractionResult` (async).

- [ ] Add `test_cross_segment_pii_is_absent_from_provider_input`: synthetic labelled full name, split phone/IIN and address cross boundaries; assert raw identifiers occur in neither final serialized segments nor source text and that segment IDs/times remain unchanged. Add `test_projection_handles_empty_and_unicode_segments` with RU/KZ and matches touching separators.
- [ ] Add parametrized `test_evidence_accepts_only_populated_source_paths`: accept literal quotes for scalar/list/medication/vital/specialty-key fields; reject unknown/empty/index-out-of-range paths, `diagnosis_code`, duplicate specialty keys, fabricated IDs, absent quotes and model-supplied timestamps/revisions. Empty evidence remains valid.
- [ ] Add `test_bad_citation_retries_once_then_fails_safely`: fake client receives exactly two requests, both use the identical masked source, no raw mapping in instructions/input, `store=False`; invalid second output returns a safe error. Transport failure makes one call. `test_demo_evidence_only_uses_fixture_source` forbids invented subsegment timestamps.

  Core assertions: `assert len(fake_client.calls) == 2`; `assert calls[0].input == calls[1].input`; `assert "010203500123" not in serialized_input`; `assert link.start == source.segments[0].start`; `assert link.transcript_revision == source.revision`.

- [ ] Run `.venv/bin/python -m pytest backend/tests/test_grounding.py backend/tests/test_pii.py backend/tests/test_providers.py -q`; confirm the new behavior fails.
- [ ] Implement offset-aware whole-text masking using the existing detector spans. Normalize segments conservatively, join with newlines and mask across boundaries; place a cross-boundary placeholder in the first touched segment and suppress every covered original character in later segments. Preserve segment boundaries/IDs/times; canonical `text` is the newline join of projected masked segments. Keep offset mappings private and ephemeral.
- [ ] Change providers to consume canonical sources and produce the extraction envelope. Reject an accidentally unmasked source at the provider boundary instead of silently sending a differently remasked string. Validate exact final segments and field paths before return, with two total validation attempts. Callback events are `(stage_key, running|done|error, attempt)` around actual network/validation work; no callback contains clinical text.
- [ ] Keep default demo extraction limited to its existing fixture. For edited synthetic browser flows, inject a test-only deterministic provider; do not turn demo into fabricated extraction of arbitrary patient text. Adapt existing provider tests to the explicit envelope and run the focused suite again.
- [ ] Review the canonical-input invariant and evidence trust boundary; report interface changes to the API worker.

This component task deliberately changes an internal provider contract. Task 4 owns all API call-site/test-double adaptations; do not deploy or run the user-facing application from the intermediate state. The focused provider suite is this task's gate, not a claim of integrated API readiness.


Read shared constraints/interfaces in .superpowers/sdd/2026-09-30-medhub-p0/context.md.

