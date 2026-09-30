## Task 6: Add frontend contracts and truthful processing/privacy panels

**Files:** Modify `src/types.ts`, `src/api.ts`; create `src/ProcessingPanel.tsx`, `src/ProcessingPanel.test.tsx`, `src/PrivacyPanel.tsx`, `src/PrivacyPanel.test.tsx`, `src/api.test.ts`.

**Interfaces:** `api.editTranscript(id, expected_revision, changes): Promise<Transcript>`; `api.audio(id, signal?: AbortSignal): Promise<Blob>`; `api.pdf(id, signal?: AbortSignal): Promise<Blob>`. `ProcessingPanel({runs}: {runs: ProcessingRun[]})`; `PrivacyPanel({transcript, document}: {transcript: Transcript; document: Document | null})`.

- [ ] Add binary API tests asserting Bearer header, token-free URL, shared 401 logout behavior, cancellation without misleading error, and no clinical browser storage writes.
- [ ] Add panel tests: `pending_has_no_fake_duration`, `running_elapsed_updates_then_stops`, `failed_stage_keeps_completed_timings`, `legacy_empty_history_is_unknown`. Privacy tests assert detected counts equal current entities, zero is not a privacy guarantee, and revision 2 with source revision 1 says `Будет отправлено при генерации` for revision 2.

  Core assertions: `expect(request.headers.get('Authorization')).toBe('Bearer test-token')`; `expect(request.url).not.toContain('test-token')`; `expect(screen.getByText(/Будет отправлено при генерации/)).toBeVisible()`.
- [ ] Run `PATH=/home/mephirious/.nvm/versions/node/v22.14.0/bin:$PATH npm test`; confirm new tests fail before implementation.
- [ ] Implement shared JSON/binary authenticated error handling and new types; retain existing `downloadDocx` behavior while sharing safe request handling. Implement panels with accessible status text, timer cleanup, rule-based masking warning and distinct current/source revisions. Unknown legacy `source_masked_text` must be labelled unknown, never reconstructed as previously sent.
- [ ] Re-run frontend tests and `npm run build` with the same Node PATH; hand off typed components without touching App or clinical editor.


Read shared constraints/interfaces in .superpowers/sdd/2026-09-30-medhub-p0/context.md.

