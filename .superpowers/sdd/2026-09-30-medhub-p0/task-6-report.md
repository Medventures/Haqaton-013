# Task 6 report — frontend contracts and processing/privacy panels

## Files changed

- `src/types.ts`: typed transcript revisions/segments, evidence, processing runs/stages, and document source metadata.
- `src/api.ts`: revision-scoped edit, authenticated audio/PDF Blob requests, shared JSON/binary status handling, cancellation propagation, and shared DOCX 401 handling.
- `src/ProcessingPanel.tsx`, `src/PrivacyPanel.tsx`: accessible, factual status and privacy displays.
- `src/api.test.ts`, `src/ProcessingPanel.test.tsx`, `src/PrivacyPanel.test.tsx`: contract and behavior checks.
- `src/DocumentEditor.test.tsx`: only the document fixture's new required metadata.

## Interfaces for integration

```ts
api.editTranscript(id: string, expected_revision: number, changes: TranscriptTextChange[]): Promise<Transcript>
api.audio(id: string, signal?: AbortSignal): Promise<Blob>
api.pdf(id: string, signal?: AbortSignal): Promise<Blob>
ProcessingPanel({ runs }: { runs: ProcessingRun[] })
PrivacyPanel({ transcript, document }: { transcript: Transcript; document: Document | null })
```

AbortError is preserved for canceled binary fetches. File requests send Bearer headers; no token or clinical payload is added to URLs or browser storage. A 401 clears the session and dispatches `medhub-unauthorized`, including DOCX.

## RED/GREEN evidence

- RED: initial `npm test` showed new API methods absent, DOCX 401 did not log out, and both panels absent. A focused run with component stubs gave 16 behavioral failures. A later DOCX compatibility test failed on its network error wording before the fix.
- GREEN: final full `PATH=/home/mephirious/.nvm/versions/node/v22.14.0/bin:$PATH npm test` passed: 7 files, 33 tests, including 18 Task 6 tests. A cancellation regression first failed with a generic `TypeError` and passed after mapping an aborted signal to `AbortError`.

## Whole-workspace verification

- Initial full `npm test` had six Task 8 PDF preview setup failures and one archived test-copy import failure. Initial `npm run build` had Task 8 `PdfPreview.tsx` TypeScript errors. Those concurrent states were reported to the controller; the controller moved the archived source snapshot outside the project and Task 8 corrected its preview files.
- Final full `npm test`: 7 files, 33 tests passed. Final `npm run build`: exit 0, production bundle built. The build emitted dependency comment and large-chunk warnings only.
- No other worker's files were edited.

## Rulings and limits

- The privacy panel labels a source snapshot as unknown whenever `source_masked_text` is null; it never substitutes the current mask as historical input. A changed current revision is labelled `Будет отправлено при генерации` and the previous source revision is shown separately.
- Processing rows show measured completed durations, a live running duration only with a real start timestamp, and no duration for pending stages. Empty legacy history is explicitly unknown.
- App/editor wiring remains Task 7 ownership. The Task 6 components and API signatures are ready to integrate.
