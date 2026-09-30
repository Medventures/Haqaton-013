# Task7 current interfaces / parallel ownership

Task6 provides named `ProcessingPanel({runs})`, `PrivacyPanel({transcript, document})`, `api.editTranscript(id, expected_revision, changes)`, `api.audio(id, signal?)`, `api.pdf(id, signal?)`. Types in src/types.ts are source of truth. Privacy/source metadata and transcript revision fields are already required on interfaces; preserve old fixtures updated by Task6.

Task8 provides named `{ PdfPreview }` from `./PdfPreview` with props `{consultationId, open, onClose}` and its own local CSS import. You own App.tsx wiring: show button beside DOCX only APPROVED/SENT_TO_MIS; render preview only for selected authorized document; close on consultation switch/logout and gate open by approved status. Task8 must not touch App.tsx/styles.css. Its own cleanup aborts fetch/render, destroys PDF.js and revokes download URLs. Worker becomes part of production bundle only when this component is imported. Keep preview optional until component review issues are resolved; main owns final browser/CSP verification.

Source evidence controls must remain usable on read-only approved documents; don't accidentally put source/playback buttons inside a disabled clinical fieldset. Evidence is AI-origin provenance, never a medical correctness claim. If an array changes/reorders, don't attach old index citation to a different current item.

Backend Task5 is running independently, preserving shared API contract. Do not edit backend. If optional AbortSignal changes to api.document/transcript/consultation are needed for request cancellation, ask controller for narrow ownership extension (Task6 ownership released only after review).

Use Node22 PATH. Source snapshots live outside project (/tmp/medhub-p0-snapshots.BPZlzl/task-7-base) so Vitest won't discover archived tests. No user records/.env/running service mutations. Browser acceptance uses isolated synthetic fixtures, never approval of user consultations.

Task6 review minor to resolve here: PrivacyPanel uses class whitespace-pre-wrap, not yet defined in styles.css. Add explicit white-space: pre-wrap plus safe wrapping for current/source masked text; preserve quote/newline formatting.
