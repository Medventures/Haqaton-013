# MedHub P0 trust workflow design

Date: 2026-09-30

## Purpose and approved scope

Implement the first release requested in `improve.txt`: a physician can see what was transcribed, inspect the source of extracted fields, understand masking and actual processing, correct transcription, and preview/download a confirmed document. The user approved this P0 scope in chat. This file is the detailed design for review before implementation planning.

Included:

1. PDF export, independently rendered from approved clinical data rather than converted from DOCX.
2. Authenticated in-app PDF preview and existing DOCX download.
3. Evidence linking AI fields to versioned transcript segments and authenticated audio seeking.
4. Actual processing stages and measured timings.
5. Detected-PII counts and masked transcript visualization.
6. Versioned transcript correction with mandatory regeneration/review after changes.

Excluded from this increment: pgvector/embeddings, semantic ICD recommendations, medication normalization, dashboard/quality analytics, arbitrary template upload, RU/KZ interface translation, diarization, streaming STT, queue infrastructure, real MIS integration, and changing authentication policy. Keep the modular monolith and the current doctor's account. Existing clinical and approved data must be preserved.

## Current baseline

React/TypeScript/Vite frontend; FastAPI/SQLAlchemy/Alembic backend; SQLite locally and PostgreSQL in Compose. Six supplied DOCX forms and the supplied ICD reference are integrated. Local Whisper small CPU/int8 and OpenAI gpt-4.1-mini have completed a real workflow. The baseline suite has 92 backend tests and 9 frontend tests. There is no usable git repository; work in the existing checkout without modifying protected git/config directories.

Clinical data is a flat `ConsultationData` object used by the editor, approval, DOCX and MIS. Transcript segments have start/end/text but no explicit IDs or revisions. Existing HTTP calls await processing; consultation summaries are polled. Original source files and recorded patient data are not fixtures and must not be copied into tests or logs.

## Design choices

### Clinical data and source evidence

Keep `ConsultationData` and document `data` compatible. Add an evidence sidecar instead of replacing clinical strings with nested `{value, evidence}` objects.

An extraction result contains:

```text
data: ConsultationData
evidence: list of {
  field_path: string,
  segment_id: string,
  quote: string
}
```

The server attaches the transcript revision and seek time from its own segment records. The LLM cannot set trusted timestamps or revisions. Accepted paths identify a populated AI field or item, such as `complaints/0`, `medications/0/dosage`, `vital_signs/temperature`, or `template_fields/p_014`. Paths referencing unknown fields, an out-of-range item, empty values, or a physician-selected diagnosis code are rejected. Specialty paths use stable keys, not current UI ordering.

The provider receives a canonical list of masked, ID-labelled segments, not raw segments. Mask the combined text before splitting it back into segment payloads so names, numbers and other matches spanning segment boundaries do not leak. Build segment projections from masking offsets; never recover raw identifier values in quotes. Existing flat masked-text storage remains available for display. No raw-to-masked identifier mapping goes to OpenAI or the browser.

Validate each evidence ID and require the quote to be a literal substring of the exact masked segment sent to the LLM. Quotes are bounded nonempty strings. Invalid citations trigger the same bounded validation retry policy as invalid clinical output; after retry failure, fail the generation safely rather than display invented evidence. Missing evidence is allowed but must display as unavailable, not verified.

Matching a source quote establishes provenance, not clinical correctness or entailment. UI wording is `Источник AI-версии` or `Фрагмент записи`, never `медицински подтверждено`. If the clinician changes the associated field, label its citation as belonging to the original AI version. Do not apply a citation from one list item to a reordered or edited item merely because its array index matches.

Existing documents get no invented citations. An empty sidecar means evidence was not recorded for that generation. Demo citations may reference only actual fixture segments; no simulated speakers or finer timestamps.

### Transcript revisions and editing

Give each stored segment a deterministic ID within the transcript and add an integer transcript revision, initially 1. IDs and times stay stable when text is corrected. This increment edits text only: users cannot change time bounds, add/remove segments, or fabricate speaker labels through the edit endpoint.

Preserve the original ASR `raw_text`. Current segments, normalized text and masked text represent the latest revision. Expose a separately named current-text value where needed so the interface does not mislabel edited content as original ASR output.

Store revision snapshots containing current segment content, normalized/masked text and detected entity metadata, with actor, source (`stt`, `demo`, `doctor`) and timestamp. Original version 1 remains available. Existing transcript rows are backfilled without retranscription or network calls. Clinical text belongs in protected revision storage, not operational logs.

Add an authenticated `PATCH /api/v1/consultations/{id}/transcript` with expected revision and segment text changes. Validate unique known segment IDs, bounded text, at least one nonempty segment and expected revision. Actual changes increment the revision; a no-op must not invalidate a document.

Allowed states: TRANSCRIBED, AI_GENERATED, REVIEWED, and FAILED with a transcript. Reject PROCESSING, APPROVED and SENT_TO_MIS. Acquire/conditionally update the consultation so generation, document saving and transcript edits cannot race successfully. The frontend requires confirmation when an existing draft or reviewed document will be invalidated and protects unsaved text on navigation.

After a transcript edit:

1. Save the new revision and re-run normalization/masking.
2. Set the consultation to TRANSCRIBED and clear processing errors.
3. Retain the previous document for history but mark it stale through its source revision.
4. Reject direct stale-document reads/saves/approval with a clear conflict; UI must hide/clear its cached editor.
5. Regeneration uses the latest transcript revision, produces fresh evidence and increments the document version.
6. Require doctor save/review and approval again.

Record the source transcript revision on every generated document. Legacy documents link to the backfilled initial revision; approved records remain locked. Regeneration must not silently merge old doctor edits into newly extracted values.

### Authenticated audio playback

Add an owner/admin-protected `GET /api/v1/consultations/{id}/audio` using registered storage keys only. Return the actual media type and `Cache-Control: no-store`. No token or medical data goes in URL query parameters.

For P0, the frontend fetches the bounded audio file with its Bearer header, creates a local blob URL and uses an HTML audio element. Source clicks highlight the transcript segment, seek to its server-derived start and offer playback. Revoke blob URLs on consultation change, logout and component cleanup. Do not preload all consultations' recordings.

Expose audio availability in the transcript/summary response. When retention has removed the file, it is missing, or the consultation used a synthetic fixture, show the source quote and timestamp with an honest `Аудиозапись недоступна` state. Do not regenerate audio or imply playback is available.

### Privacy visualization

Show detected counts by entity type, the current masked text and the transcript revision used. Zero is a detected count, not proof that no personal information remains. Clearly state that masking is rule-based and may miss data.

Distinguish `Будет отправлено при генерации` from a successful generation's actual source revision. If the transcript has been edited, do not claim its new text was already sent. Audio remains local in this architecture. Manual transcript edits always trigger fresh masking before generation.

### Processing stages

Retain the existing top-level lifecycle and awaited HTTP operations. Add persisted stage records with operation/run ID, stage key, status, start/end timestamps, measured duration and a safe error code.

Actual stages cover upload completion, STT, normalization, PII masking, LLM extraction and output validation. For model download/loading, report an indeterminate preparation state only where the provider actually signals it; do not pretend to know download or inference percentage. Existing records without timing use unknown values rather than fabricated elapsed times.

Display stage completion and elapsed time. A stage counter is acceptable; a percentage must not imply elapsed-work accuracy. Completed rows have measured times, the running row has a live elapsed timer, and future rows are pending. If an operation fails, retain the completed stage timings and identify the failed stage with a safe localized message.

Polling starts while the user action is pending, not only after the initial HTTP response, so long processing is visible. Refresh resumes polling from persisted state. On API restart mark interrupted operations/active stages failed using the existing single-instance recovery policy. A distributed queue remains explicitly out of scope.

### PDF and DOCX

Use the same approved clinical snapshot and approval metadata for both outputs. Extract a common field/section projection from the existing six-form catalog so PDF preserves every populated core field, medication, vital, specialty value and physician-selected ICD code. Do not infer normal findings from source form alternatives.

Keep the original DOCX-based renderer. Add an independent PDF renderer using ReportLab, a packaged licensed Unicode regular/bold font covering Russian and Kazakh, automatic paragraph wrapping, pagination, consistent headers/footers and approval metadata. Escape text used in markup-capable PDF paragraphs and handle unsupported control characters. Empty values remain `Не указано`; signatures remain explicitly unsigned. Do not invent UMC branding or imply certification of the layout.

The PDF may have a clean MedHub layout rather than match the source DOCX pixel for pixel. It is rendered from approved JSON and catalog metadata, never through LibreOffice/DOCX conversion. The current catalog still reads the supplied DOCX files for its field prompts/mapping; arbitrary template changes are not supported.

Add `GET /api/v1/consultations/{id}/document.pdf`, with the same ownership and APPROVED/SENT_TO_MIS guards as DOCX. Return PDF bytes and no-store headers. Existing approved records must work with missing optional new metadata. Neither renderer uses the editable working copy.

Preview fetches the PDF through authenticated API and displays it through locally bundled PDF.js. Use no public third-party document viewer, no tokens in URLs and no CDN scripts. Bundle the worker, adjust worker CSP narrowly where required, and retain `object-src 'none'`. Preview and download use the same fetched bytes while open. Provide loading/error/retry, page navigation and a download action; keep the editor read-only and approvals unchanged.

Immutable clinical data is guaranteed by the existing approval lifecycle. Byte-identical historical artifacts across later renderer/template upgrades are not promised by P0; template/artifact versioning remains a subsequent increment.

## Persistence and migration

Use an additive Alembic migration compatible with SQLite and PostgreSQL. New storage includes transcript revision/segment IDs, protected transcript revision snapshots, document source revision/evidence and processing stage state. Preserve existing users, consultations, approved JSON, audits and source files. No new external API call occurs during migration.

Backfill existing transcripts/documents deterministically; avoid creating false evidence/timings. Test migration from the current revision with representative old approved and unapproved rows. Stop the owned local API, create a verified recoverable database backup, apply the migration, then restart only after tests pass. Do not change the user's API key, password or database type. Keep startup recovery's single-process limitation explicit.

## Frontend structure

Extract focused components from the large workspace instead of expanding its monolithic JSX: TranscriptPanel/editor and player, SourceEvidence, PrivacyPanel, ProcessingPanel, PdfPreview. Keep the existing design language, template picker and clinical editor controls.

Shared state includes selected consultation, transcript revision, document source revision, pending transcript edits and current evidence selection. Clear clinical caches on invalidation and avoid showing cached drafts whose status/revision no longer permits them. Preserve normal document unsaved-edit protection and existing intentional-regeneration reset behavior.

Use responsive containers and wrapping for long source prompts/quotes; fix the known mobile overflow in the touched workflow. Controls need accessible labels, keyboard support and visible loading/error/disabled states. Evidence and privacy details must not leak into URLs or persistent browser storage.

## Acceptance checks

1. All existing backend/frontend tests remain green, with fixtures adapted to explicit new contracts where needed.
2. Migrations preserve existing approved and unapproved consultations, original text and document values.
3. PDF contains every applicable approved core and specialty value for all six forms, supports RU/KZ characters, special characters and long multipage text, and excludes unsaved working values.
4. PDF/audio endpoints reject unauthenticated and other-doctor access. PDF remains unavailable before approval; demo/expired audio has a clear fallback.
5. Preview renders an authenticated PDF; download succeeds; no token is put in a URL; blob/worker resources clean up on navigation.
6. Evidence cannot cite unknown IDs/fields, wrong revisions or text absent from the exact final masked LLM input. Cross-segment PII test cases remain masked.
7. Transcript edits preserve originals, increment revision, remask data, reject stale concurrent edits, invalidate old drafts/citations and require renewed review. Approved/exported edits are rejected.
8. UI clears stale cached documents, prevents accidental loss of unsaved text and correctly distinguishes edited values from AI-source evidence.
9. Actual stage transitions, durations, failures and restart recovery are observable without clinical payloads in logs or fabricated progress.
10. Privacy counts match the current revision; copy does not promise complete anonymization or claim an unsent revision was transmitted.
11. Browser synthetic acceptance covers correction → regeneration → evidence/seek → review → approval → preview → PDF/DOCX. Mobile view has no horizontal overflow in this workflow.
12. Live-provider checks use synthetic input unless an existing user consultation is explicitly selected for a requested end-to-end verification. Do not approve or export the user's consultation on their behalf.

## Sources and remaining limits

Primary requirements: `improve.txt`. Current implementation: `backend/app`, `src`, deployment files and `docs/system-description.md`. Technical reference: OpenAI Structured Outputs, ReportLab Unicode/Platypus docs, PDF.js API docs. Structured output validates shape; it does not establish clinical accuracy. Source quote matching validates provenance only. Regex PII limitations, unverified real MIS and the current weak user-selected password are not resolved by this UX increment.

## Review status

P0 scope and detailed design approved by the user in chat on 2026-09-30. Implementation plan review follows this approval; no P0 application code has been changed at this stage.
