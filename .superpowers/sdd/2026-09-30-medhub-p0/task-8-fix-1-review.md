# Task8 fixes isolated re-review

Read original task-8-review-verdict.md, updated task-8-report.md and re-review-prompt.md. Scope: cleanup promise order/failures and narrow .mjs MIME handling. Focused8/full35/build0; disposable Nginx RED octetstream, GREEN both configs JavaScript preserving headers/API routes/JS/CSS (report). No Task7 App/style changes in this package.

## src/PdfPreview.tsx
```diff
--- /tmp/medhub-p0-snapshots.BPZlzl/task-8-fix-base/src/PdfPreview.tsx	2026-09-30 14:33:11.568968071 +0500
+++ src/PdfPreview.tsx	2026-09-30 14:32:54.956761916 +0500
@@ -38,35 +38,38 @@
     setPainted(false)
     setPageNumber(1)
     async function load() {
       try {
         const blob = await api.pdf(consultationId, controller.signal)
         if (!active) return
         const buffer = await blob.arrayBuffer()
         if (!active) return
         loadingTask = getDocument({ data: new Uint8Array(buffer) })
         const document = await loadingTask.promise
-        if (!active) { void document.cleanup(); return }
+        if (!active) { void document.cleanup().catch(() => {}); return }
         pdfDocument = document
         setState({ kind: 'ready', blob, document })
       } catch {
         if (active) setState({ kind: 'error' })
       }
     }
     void load()
     return () => {
       active = false
       controller.abort()
       renderTaskRef.current?.cancel()
       renderTaskRef.current = null
-      if (pdfDocument) void pdfDocument.cleanup()
-      if (loadingTask) void loadingTask.destroy()
+      if (loadingTask) {
+        void loadingTask.destroy().catch(() => {}).then(() => pdfDocument?.cleanup()).catch(() => {})
+      } else if (pdfDocument) {
+        void pdfDocument.cleanup().catch(() => {})
+      }
     }
   }, [consultationId, attempt])
 
   useEffect(() => {
     const box = pageBoxRef.current
     if (!box || typeof ResizeObserver === 'undefined') return
     const observer = new ResizeObserver(entries => {
       const width = Math.floor(entries[0]?.contentRect.width ?? 0)
       if (width > 0) setPageWidth(width)
     })

```

## src/PdfPreview.test.tsx
```diff
--- /tmp/medhub-p0-snapshots.BPZlzl/task-8-fix-base/src/PdfPreview.test.tsx	2026-09-30 14:33:11.617968679 +0500
+++ src/PdfPreview.test.tsx	2026-09-30 14:33:19.524067005 +0500
@@ -11,22 +11,22 @@
 function deferred<T>() {
   let resolve!: (value: T) => void
   let reject!: (reason: unknown) => void
   const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
   return { promise, resolve, reject }
 }
 
 function setupDocument(renderPromise: Promise<void> = Promise.resolve()) {
   const renderTask = { promise: renderPromise, cancel: vi.fn() }
   const page = { getViewport: vi.fn(({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale })), render: vi.fn(() => renderTask) }
-  const document = { numPages: 2, getPage: vi.fn(async () => page), cleanup: vi.fn(async () => undefined) }
-  const loadingTask = { promise: Promise.resolve(document), destroy: vi.fn(async () => undefined) }
+  const document = { numPages: 2, getPage: vi.fn(async () => page), cleanup: vi.fn((): Promise<void> => Promise.resolve()) }
+  const loadingTask = { promise: Promise.resolve(document), destroy: vi.fn((): Promise<void> => Promise.resolve()) }
   pdf.getDocument.mockReturnValue(loadingTask)
   return { renderTask, page, document, loadingTask }
 }
 
 beforeEach(() => {
   vi.clearAllMocks()
   Object.defineProperty(Blob.prototype, 'arrayBuffer', { configurable: true, value: async () => bytes.buffer.slice(0) })
   vi.mocked(api.pdf).mockResolvedValue(new Blob([bytes], { type: 'application/pdf' }))
   vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as CanvasRenderingContext2D)
 })
@@ -109,31 +109,46 @@
 
   it('cancels rendering and destroys the old PDF on consultation switch', async () => {
     const stuck = deferred<void>()
     const first = setupDocument(stuck.promise)
     const view = render(<PdfPreview consultationId="approved-1" open onClose={vi.fn()} />)
     await waitFor(() => expect(first.page.render).toHaveBeenCalledTimes(1))
     const second = setupDocument()
     view.rerender(<PdfPreview consultationId="approved-2" open onClose={vi.fn()} />)
     expect(first.renderTask.cancel).toHaveBeenCalled()
     expect(first.loadingTask.destroy).toHaveBeenCalled()
-    expect(first.document.cleanup).toHaveBeenCalled()
+    await waitFor(() => expect(first.document.cleanup).toHaveBeenCalled())
     await waitFor(() => expect(second.page.render).toHaveBeenCalledTimes(1))
     expect(api.pdf).toHaveBeenNthCalledWith(2, 'approved-2', expect.any(AbortSignal))
     stuck.resolve()
     await Promise.resolve()
     expect(first.page.render).toHaveBeenCalledTimes(1)
     expect(screen.getByText('Страница 1 из 2')).toBeInTheDocument()
   })
 
   it('closes with Escape and releases the document on logout unmount', async () => {
     const first = setupDocument()
     const onClose = vi.fn()
     const view = render(<PdfPreview consultationId="approved-1" open onClose={onClose} />)
     await screen.findByText('Страница 1 из 2')
     fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
     await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
     view.unmount()
     expect(first.loadingTask.destroy).toHaveBeenCalled()
-    expect(first.document.cleanup).toHaveBeenCalled()
+    await waitFor(() => expect(first.document.cleanup).toHaveBeenCalled())
+  })
+
+  it('waits for worker destruction before cleaning up a rendering document', async () => {
+    const rendering = deferred<void>()
+    const destroying = deferred<void>()
+    const first = setupDocument(rendering.promise)
+    first.loadingTask.destroy.mockReturnValue(destroying.promise)
+    const view = render(<PdfPreview consultationId="approved-1" open onClose={vi.fn()} />)
+    await waitFor(() => expect(first.page.render).toHaveBeenCalledTimes(1))
+    view.unmount()
+    expect(first.renderTask.cancel).toHaveBeenCalled()
+    expect(first.loadingTask.destroy).toHaveBeenCalled()
+    expect(first.document.cleanup).not.toHaveBeenCalled()
+    destroying.resolve()
+    await waitFor(() => expect(first.document.cleanup).toHaveBeenCalled())
   })
 })

```

## deploy/nginx.conf
Original baseline→current (includes previously approved worker-src self)
```diff
--- /tmp/medhub-p0-snapshots.BPZlzl/task-8-base/deploy/nginx.conf	2026-09-30 14:22:18.128816792 +0500
+++ deploy/nginx.conf	2026-09-30 14:38:29.474008753 +0500
@@ -4,30 +4,35 @@
     root /usr/share/nginx/html;
     index index.html;
     server_tokens off;
     client_max_body_size 51m;
 
     add_header X-Content-Type-Options nosniff always;
     add_header X-Frame-Options DENY always;
     add_header Referrer-Policy no-referrer always;
     add_header Cache-Control "no-store" always;
     add_header Permissions-Policy "microphone=(self), camera=(), geolocation=()" always;
-    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'" always;
+    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; worker-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'" always;
 
     location /api/ {
         proxy_pass http://api:8000;
         proxy_http_version 1.1;
         proxy_set_header Host $host;
         proxy_set_header X-Real-IP $remote_addr;
         proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
         proxy_set_header X-Forwarded-Proto $scheme;
         proxy_read_timeout 900s;
         proxy_send_timeout 900s;
         proxy_buffering off;
         # Consultations and tokens must not appear in caches or access logs.
         access_log off;
     }
 
+    location ~ ^/assets/[^/]+\.mjs$ {
+        types { application/javascript mjs; }
+        try_files $uri =404;
+    }
+
     location / {
         try_files $uri $uri/ /index.html;
     }
 }

```

## deploy/nginx.tls.conf
Original baseline→current (includes previously approved worker-src self)
```diff
--- /tmp/medhub-p0-snapshots.BPZlzl/task-8-base/deploy/nginx.tls.conf	2026-09-30 14:22:18.128873168 +0500
+++ deploy/nginx.tls.conf	2026-09-30 14:38:29.515009283 +0500
@@ -14,29 +14,34 @@
     root /usr/share/nginx/html;
     index index.html;
     server_tokens off;
     client_max_body_size 51m;
     add_header Strict-Transport-Security "max-age=31536000" always;
     add_header X-Content-Type-Options nosniff always;
     add_header X-Frame-Options DENY always;
     add_header Referrer-Policy no-referrer always;
     add_header Cache-Control "no-store" always;
     add_header Permissions-Policy "microphone=(self), camera=(), geolocation=()" always;
-    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'" always;
+    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; worker-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'" always;
 
     location /api/ {
         proxy_pass http://api:8000;
         proxy_http_version 1.1;
         proxy_set_header Host $host;
         proxy_set_header X-Real-IP $remote_addr;
         proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
         proxy_set_header X-Forwarded-Proto $scheme;
         proxy_read_timeout 900s;
         proxy_send_timeout 900s;
         proxy_buffering off;
         access_log off;
     }
 
+    location ~ ^/assets/[^/]+\.mjs$ {
+        types { application/javascript mjs; }
+        try_files $uri =404;
+    }
+
     location / {
         try_files $uri $uri/ /index.html;
     }
 }

```
