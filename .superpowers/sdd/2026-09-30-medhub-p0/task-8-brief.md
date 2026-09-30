## Task 8: Add local authenticated PDF preview

**Files:** Create `src/PdfPreview.tsx`, `src/PdfPreview.test.tsx`; modify `src/App.tsx`, `src/styles.css`, `package.json`, `package-lock.json`, `deploy/nginx.conf`, `deploy/nginx.tls.conf`.

**Interfaces:** `PdfPreview({consultationId, open, onClose}: {consultationId: string; open: boolean; onClose: () => void})` loads `api.pdf` once per opening and uses that Blob for preview and download.

- [ ] Add tests for loading/error/retry, page navigation, approved-only opening, download using the same fetched bytes, and close/logout/consultation switch cancelling pending fetch/render tasks. Assert old pages never paint into the next consultation and PDF.js loading tasks/documents are destroyed.

  Core assertions: `expect(api.pdf).toHaveBeenCalledTimes(1)` for preview plus download in one opening; `expect(downloadedHash).toBe(previewHash)`; `expect(renderTask.cancel).toHaveBeenCalled()`; `expect(loadingTask.destroy).toHaveBeenCalled()` after closure.
- [ ] Run frontend tests to observe failures. Add a supported PDF.js release using official documentation and lock it in `package-lock.json`; bundle its worker through Vite, never CDN or external viewer.
- [ ] Implement responsive canvas preview from an ArrayBuffer copy while retaining the original Blob for download (PDF.js may transfer the typed array). Cancel/destroy render/loading resources and revoke download URLs; support keyboard close, labelled previous/next page and retry.
- [ ] Add preview/download actions beside existing DOCX actions only for APPROVED/SENT_TO_MIS. Add the narrow worker CSP required by the actual bundled worker (prefer `worker-src 'self'`; add `blob:` only if proven necessary); retain `object-src 'none'`, frame restrictions and token-free URLs in both Nginx configurations.
- [ ] Run frontend tests/build and a synthetic browser preview with production CSP: first page paints, next page paints, download has the same byte hash as the preview response, no external asset request occurs, cleanup works. Check mobile dialog containment.


Read shared constraints/interfaces in .superpowers/sdd/2026-09-30-medhub-p0/context.md.

