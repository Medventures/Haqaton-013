## Task 7: Integrate transcript correction, source evidence and audio

**Files:** Create `src/TranscriptPanel.tsx`, `src/TranscriptPanel.test.tsx`, `src/SourceEvidence.tsx`, `src/SourceEvidence.test.tsx`, `src/Workspace.test.tsx`; modify `src/App.tsx`, `src/DocumentEditor.tsx`, `src/DocumentEditor.test.tsx`, `src/styles.css`.

**Interfaces:** `SourceSelection = {segmentId: string; start: number; quote: string}`; `SourceEvidence({fieldPath, aiData, currentData, evidence, onSelect})` consumes stable AI-sidecar paths; `TranscriptPanel({consultationId, transcript, editable, selection, onSave, onDirtyChange})` owns editing/player state and calls `onSave(changes, expectedRevision): Promise<void>`.

- [ ] Add `transcript_save_confirms_draft_invalidation_and_clears_cached_editor`: successful edit removes document query cache, hides editor before refetch and updates transcript revision; a delayed old fetch cannot resurrect it. A 409 retains unsaved edits and asks the user to reload/resolve rather than silently overwriting.
- [ ] Add tests for navigation/logout dirty guards, APPROVED/SENT_TO_MIS read-only, preserved dirty clinical edits on ordinary refetch, explicit regeneration reset, and polling while the action promise is pending (not only after PROCESSING has already been fetched).
- [ ] Add evidence tests for scalar changes, reordered/deleted/duplicated medications, list insertion and specialty reordering. Citations use stable specialty keys; for clinical arrays, if the containing array differs from the AI snapshot, do not attach index-based links to current items. Show detached original AI value/quote with `Источник AI-версии`, not a verified-current-field badge.
- [ ] Add `audio_selection_uses_server_time_and_cancels_on_switch`: click selects/highlights correct segment and seeks after metadata loads; missing audio keeps quote/time visible; late fetch after consultation switch/logout is discarded and every created blob URL is revoked on cleanup.

  Core assertions: `expect(screen.queryByRole('form', {name: /документ/i})).not.toBeInTheDocument()` after invalidation; `expect(audio.currentTime).toBe(selectedEvidence.start)`; `expect(revokeObjectURL).toHaveBeenCalledWith(oldUrl)`; `expect(screen.getByText(/Источник AI-версии/)).toBeVisible()` for changed values.
- [ ] Run the frontend suite and verify new tests fail; implement focused transcript/editor/player and evidence components with labelled controls, text-only changes, explicit save confirmation and unavailable-source fallback. Evidence for all clinical field classes must be reachable without converting the clinical schema.
- [ ] Integrate processing/privacy panels and query refresh. Poll consultation status while local transcribe/generate is pending or server status is PROCESSING; on refresh recover from persisted state. Do not poll all consultations' audio or retain raw text in persistent browser storage.
- [ ] Gate cached editor display using status and matching transcript/source revision; cancel old document requests on invalidation. Connect source selection to transcript highlight/audio seeking and retain confirmed regeneration semantics.
- [ ] Fix long prompt/quote wrapping with scoped `min-width: 0` and `overflow-wrap: anywhere`; verify keyboard access and no horizontal overflow at 375px. Run frontend tests and production build, then review workspace state transitions.


Read shared constraints/interfaces in .superpowers/sdd/2026-09-30-medhub-p0/context.md.

