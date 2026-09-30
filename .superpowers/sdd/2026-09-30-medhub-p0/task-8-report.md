# Task 8 — standalone PDF preview

## Ownership and deliverable

Implemented `src/PdfPreview.tsx`, `src/PdfPreview.css`, `src/PdfPreview.test.tsx`; pinned `pdfjs-dist@6.3.289` in `package.json` and `package-lock.json`; added `worker-src 'self'` to `deploy/nginx.conf` and `deploy/nginx.tls.conf`. Did not edit `App.tsx`, `styles.css`, `api.ts`, or `types.ts` because Tasks 6–7 own those files during parallel execution.

The component interface is `PdfPreview({ consultationId, open, onClose })`. It calls Task 6's `api.pdf(id, AbortSignal)`, keeps the returned Blob for download, and gives PDF.js an ArrayBuffer copy. A keyed child session prevents the previous consultation's state and canvas from appearing after switching IDs. Fetch abort, render cancellation, PDF document cleanup, loading-task destruction, and object URL revocation occur on close, switch, retry, or unmount. PDF.js worker is a Vite `?url` asset from the installed package, not a CDN script or viewer.

## RED → GREEN evidence

- RED: `PATH=/home/mephirious/.nvm/versions/node/v22.14.0/bin:$PATH npm test -- src/PdfPreview.test.tsx` exited 1 because `./PdfPreview` did not exist (6 tests specified before implementation).
- Initial GREEN attempt exposed the jsdom Blob limitation: jsdom's Blob has no `arrayBuffer()`. Confirmed with a standalone jsdom probe; added a test-only Blob method fixture. This was a harness issue, not a product fallback.
- After implementation: focused tests passed 6/6, then 7/7 after adding pending PDF.js loading-task destruction coverage.
- A source review found that PDF.js 6 `PDFDocumentProxy.cleanup()` rejects while a page is rendering. Added a test requiring `loadingTask.destroy()` to finish before document cleanup: RED 1/8 (`cleanup` called too early), then GREEN 8/8 after sequencing the operations and handling rejected cleanup promises.
- Fresh full frontend suite after this fix: `npm test -- --reporter=dot` passed 35/35 across 7 files. Fresh `npm run build` passed, including TypeScript and Vite, on Node 22.14.0. Vite reported a nonfatal bundle-size warning and third-party comment warnings.

The 8 focused tests cover closed state (no fetch), one fetch per opening, page navigation and button bounds, error/retry, same Blob/bytes for preview and download, abort before fetch resolves, destruction during PDF.js loading, render cancellation/document cleanup on consultation switch, Escape/unmount cleanup, and safe cleanup order during rendering.

## Source and CSP ruling

Used the [official PDF.js browser example](https://mozilla.github.io/pdf.js/examples/) for the `getDocument` loading task and render flow and the [official PDF.js release list](https://github.com/mozilla/pdf.js/releases) to select stable version 6.3.289. In this release `PDFDocumentProxy` has `cleanup()` while `PDFDocumentLoadingTask` has `destroy()`; the component calls both at their respective lifecycle boundaries. The worker URL is emitted from the local package by Vite. Both Nginx CSPs add only `worker-src 'self'` and retain `object-src 'none'` and `frame-ancestors 'none'`.

Independent review identified that inherited Nginx `mime.types` lacks `.mjs`; with `X-Content-Type-Options: nosniff`, the emitted worker would be blocked as `application/octet-stream`. A disposable local Nginx check first reproduced that exact RED response from `deploy/nginx.conf`. Both HTTP and TLS server blocks now route only `/assets/*.mjs` through a local MIME mapping to `application/javascript`, with `try_files` returning 404 for missing workers. The same runtime check then passed for both configs: worker JavaScript MIME, normal `.js` and `.css` MIME, API `.mjs` paths still proxied, CSP (`worker-src 'self'`, `object-src 'none'`, `frame-ancestors 'none'`), `nosniff`, and frame denial retained. This check used a disposable static root and no user process or data.

## Integration handoff

Task 7 should import `PdfPreview`, add `pdfPreviewOpen` state in Workspace, show a `Просмотр PDF` button beside `Скачать DOCX` only for `APPROVED` and `SENT_TO_MIS`, and render `<PdfPreview consultationId={selectedId} open={pdfPreviewOpen && approvedStatus} onClose={() => setPdfPreviewOpen(false)} />` while selectedId is non-null. Close the state on consultation switch and logout. Component keying/unmount handles cleanup even if the parent changes ID while open.

Current production build does not emit the worker because `App.tsx` has not yet imported this standalone component; tree shaking removes it. The Task 9 synthetic browser check must run after Task 7 wiring and verify first/next page paint, same downloaded response bytes, no external asset request, close/switch cleanup, and mobile dialog containment under the deployed CSP. This worker did not access the live user database, API process, `.env`, or protected records.
