# Task8 standalone preview review package

App wiring deferred to Task7, production-CSP browser acceptance after backend integration. New stylesheet is local to preview.

## src/PdfPreview.tsx
```diff
--- before/src/PdfPreview.tsx
+++ after/src/PdfPreview.tsx
@@ -0,0 +1,166 @@
+import { useEffect, useRef, useState } from 'react'
+import * as Dialog from '@radix-ui/react-dialog'
+import { Download, X } from 'lucide-react'
+import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
+import type { PDFDocumentLoadingTask, PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
+import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
+import { api } from './api'
+import { Button } from './ui'
+import './PdfPreview.css'
+
+GlobalWorkerOptions.workerSrc = workerUrl
+
+type Ready = { kind: 'ready'; blob: Blob; document: PDFDocumentProxy }
+type PreviewState = { kind: 'loading' } | { kind: 'error' } | Ready
+
+export function PdfPreview({ consultationId, open, onClose }: { consultationId: string; open: boolean; onClose: () => void }) {
+  return open ? <PreviewSession key={consultationId} consultationId={consultationId} onClose={onClose} /> : null
+}
+
+function PreviewSession({ consultationId, onClose }: { consultationId: string; onClose: () => void }) {
+  const [attempt, setAttempt] = useState(0)
+  const [state, setState] = useState<PreviewState>({ kind: 'loading' })
+  const [pageNumber, setPageNumber] = useState(1)
+  const [pageWidth, setPageWidth] = useState(720)
+  const [painted, setPainted] = useState(false)
+  const canvasRef = useRef<HTMLCanvasElement>(null)
+  const pageBoxRef = useRef<HTMLDivElement>(null)
+  const renderTaskRef = useRef<RenderTask | null>(null)
+  const downloadUrls = useRef(new Set<string>())
+  const revokeTimers = useRef(new Set<ReturnType<typeof setTimeout>>())
+
+  useEffect(() => {
+    let active = true
+    const controller = new AbortController()
+    let loadingTask: PDFDocumentLoadingTask | null = null
+    let pdfDocument: PDFDocumentProxy | null = null
+    setState({ kind: 'loading' })
+    setPainted(false)
+    setPageNumber(1)
+    async function load() {
+      try {
+        const blob = await api.pdf(consultationId, controller.signal)
+        if (!active) return
+        const buffer = await blob.arrayBuffer()
+        if (!active) return
+        loadingTask = getDocument({ data: new Uint8Array(buffer) })
+        const document = await loadingTask.promise
+        if (!active) { void document.cleanup(); return }
+        pdfDocument = document
+        setState({ kind: 'ready', blob, document })
+      } catch {
+        if (active) setState({ kind: 'error' })
+      }
+    }
+    void load()
+    return () => {
+      active = false
+      controller.abort()
+      renderTaskRef.current?.cancel()
+      renderTaskRef.current = null
+      if (pdfDocument) void pdfDocument.cleanup()
+      if (loadingTask) void loadingTask.destroy()
+    }
+  }, [consultationId, attempt])
+
+  useEffect(() => {
+    const box = pageBoxRef.current
+    if (!box || typeof ResizeObserver === 'undefined') return
+    const observer = new ResizeObserver(entries => {
+      const width = Math.floor(entries[0]?.contentRect.width ?? 0)
+      if (width > 0) setPageWidth(width)
+    })
+    observer.observe(box)
+    return () => observer.disconnect()
+  }, [state.kind])
+
+  useEffect(() => {
+    if (state.kind !== 'ready') return
+    const activeDocument = state.document
+    let active = true
+    let renderTask: RenderTask | null = null
+    setPainted(false)
+    async function paint() {
+      try {
+        const page = await activeDocument.getPage(pageNumber)
+        if (!active) return
+        const canvas = canvasRef.current
+        const context = canvas?.getContext('2d')
+        if (!canvas || !context) throw new Error('Canvas unavailable')
+        const base = page.getViewport({ scale: 1 })
+        const scale = Math.min(pageWidth, 900) / base.width
+        const cssViewport = page.getViewport({ scale })
+        const viewport = page.getViewport({ scale: scale * (window.devicePixelRatio || 1) })
+        canvas.width = Math.ceil(viewport.width)
+        canvas.height = Math.ceil(viewport.height)
+        canvas.style.width = `${Math.ceil(cssViewport.width)}px`
+        const task = page.render({ canvas, canvasContext: context, viewport })
+        renderTask = task
+        renderTaskRef.current = task
+        await task.promise
+        if (active) setPainted(true)
+      } catch {
+        if (active) setState({ kind: 'error' })
+      }
+    }
+    void paint()
+    return () => {
+      active = false
+      renderTask?.cancel()
+      if (renderTaskRef.current === renderTask) renderTaskRef.current = null
+    }
+  }, [state, pageNumber, pageWidth])
+
+  useEffect(() => () => {
+    for (const timer of revokeTimers.current) clearTimeout(timer)
+    for (const url of downloadUrls.current) URL.revokeObjectURL(url)
+    revokeTimers.current.clear()
+    downloadUrls.current.clear()
+  }, [])
+
+  function download() {
+    if (state.kind !== 'ready') return
+    const url = URL.createObjectURL(state.blob)
+    downloadUrls.current.add(url)
+    const anchor = window.document.createElement('a')
+    anchor.href = url
+    anchor.download = `consultation-${consultationId}.pdf`
+    window.document.body.append(anchor)
+    anchor.click()
+    anchor.remove()
+    const timer = window.setTimeout(() => {
+      URL.revokeObjectURL(url)
+      downloadUrls.current.delete(url)
+      revokeTimers.current.delete(timer)
+    }, 30_000)
+    revokeTimers.current.add(timer)
+  }
+
+  return <Dialog.Root open onOpenChange={next => { if (!next) onClose() }}>
+    <Dialog.Portal>
+      <Dialog.Overlay className="dialog-overlay" />
+      <Dialog.Content className="pdf-preview-dialog" aria-describedby="pdf-preview-description">
+        <header className="pdf-preview-header">
+          <div><Dialog.Title>Просмотр PDF</Dialog.Title><Dialog.Description id="pdf-preview-description">Подтверждённый документ консультации</Dialog.Description></div>
+          <Dialog.Close asChild><Button variant="ghost" size="icon" aria-label="Закрыть просмотр"><X size={18} /></Button></Dialog.Close>
+        </header>
+        {state.kind === 'loading' && <div className="pdf-preview-message" role="status">Загружаем PDF…</div>}
+        {state.kind === 'error' && <div className="pdf-preview-message"><p role="alert">Не удалось загрузить PDF.</p><Button onClick={() => setAttempt(value => value + 1)}>Повторить</Button></div>}
+        {state.kind === 'ready' && <>
+          <div className="pdf-preview-toolbar">
+            <div className="pdf-preview-navigation">
+              <Button variant="secondary" size="sm" aria-label="Предыдущая страница" disabled={pageNumber === 1} onClick={() => setPageNumber(value => value - 1)}>Назад</Button>
+              <span aria-live="polite">Страница {pageNumber} из {state.document.numPages}</span>
+              <Button variant="secondary" size="sm" aria-label="Следующая страница" disabled={pageNumber === state.document.numPages} onClick={() => setPageNumber(value => value + 1)}>Вперёд</Button>
+            </div>
+            <Button size="sm" onClick={download}><Download size={16} /> Скачать PDF</Button>
+          </div>
+          <div className="pdf-preview-pages" ref={pageBoxRef}>
+            {!painted && <span className="pdf-preview-painting" role="status">Рисуем страницу…</span>}
+            <canvas key={pageNumber} ref={canvasRef} aria-label={`Страница ${pageNumber} PDF`} />
+          </div>
+        </>}
+      </Dialog.Content>
+    </Dialog.Portal>
+  </Dialog.Root>
+}

```

## src/PdfPreview.test.tsx
```diff
--- before/src/PdfPreview.test.tsx
+++ after/src/PdfPreview.test.tsx
@@ -0,0 +1,139 @@
+import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
+import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
+import { api } from './api'
+import { PdfPreview } from './PdfPreview'
+
+const pdf = vi.hoisted(() => ({ getDocument: vi.fn() }))
+vi.mock('pdfjs-dist', () => ({ getDocument: pdf.getDocument, GlobalWorkerOptions: { workerSrc: '' } }))
+vi.mock('./api', () => ({ api: { pdf: vi.fn() } }))
+
+const bytes = new Uint8Array([37, 80, 68, 70, 45, 49, 46, 55])
+function deferred<T>() {
+  let resolve!: (value: T) => void
+  let reject!: (reason: unknown) => void
+  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
+  return { promise, resolve, reject }
+}
+
+function setupDocument(renderPromise: Promise<void> = Promise.resolve()) {
+  const renderTask = { promise: renderPromise, cancel: vi.fn() }
+  const page = { getViewport: vi.fn(({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale })), render: vi.fn(() => renderTask) }
+  const document = { numPages: 2, getPage: vi.fn(async () => page), cleanup: vi.fn(async () => undefined) }
+  const loadingTask = { promise: Promise.resolve(document), destroy: vi.fn(async () => undefined) }
+  pdf.getDocument.mockReturnValue(loadingTask)
+  return { renderTask, page, document, loadingTask }
+}
+
+beforeEach(() => {
+  vi.clearAllMocks()
+  Object.defineProperty(Blob.prototype, 'arrayBuffer', { configurable: true, value: async () => bytes.buffer.slice(0) })
+  vi.mocked(api.pdf).mockResolvedValue(new Blob([bytes], { type: 'application/pdf' }))
+  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as CanvasRenderingContext2D)
+})
+afterEach(() => { cleanup(); Reflect.deleteProperty(Blob.prototype, 'arrayBuffer'); vi.restoreAllMocks(); vi.unstubAllGlobals() })
+
+describe('authenticated PDF preview', () => {
+  it('loads once per opening and navigates rendered pages', async () => {
+    const { document, page } = setupDocument()
+    const view = render(<PdfPreview consultationId="approved-1" open={false} onClose={vi.fn()} />)
+    expect(api.pdf).not.toHaveBeenCalled()
+    view.rerender(<PdfPreview consultationId="approved-1" open onClose={vi.fn()} />)
+    await waitFor(() => expect(page.render).toHaveBeenCalledTimes(1))
+    expect(api.pdf).toHaveBeenCalledTimes(1)
+    expect(document.getPage).toHaveBeenCalledWith(1)
+    expect(screen.getByText('Страница 1 из 2')).toBeInTheDocument()
+    expect(screen.getByRole('button', { name: 'Предыдущая страница' })).toBeDisabled()
+    fireEvent.click(screen.getByRole('button', { name: 'Следующая страница' }))
+    await waitFor(() => expect(document.getPage).toHaveBeenCalledWith(2))
+    expect(screen.getByText('Страница 2 из 2')).toBeInTheDocument()
+    expect(screen.getByRole('button', { name: 'Следующая страница' })).toBeDisabled()
+  })
+
+  it('shows an error and retries with a fresh authenticated request', async () => {
+    setupDocument()
+    vi.mocked(api.pdf).mockRejectedValueOnce(new Error('network'))
+    render(<PdfPreview consultationId="approved-1" open onClose={vi.fn()} />)
+    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось загрузить PDF')
+    expect(pdf.getDocument).not.toHaveBeenCalled()
+    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }))
+    await waitFor(() => expect(screen.getByText('Страница 1 из 2')).toBeInTheDocument())
+    expect(api.pdf).toHaveBeenCalledTimes(2)
+  })
+
+  it('downloads the same fetched Blob without a second PDF request', async () => {
+    setupDocument()
+    const urls: Blob[] = []
+    const revoke = vi.fn()
+    vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn((blob: Blob) => { urls.push(blob); return 'blob:local-pdf' }), revokeObjectURL: revoke })
+    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
+    const view = render(<PdfPreview consultationId="approved-1" open onClose={vi.fn()} />)
+    await screen.findByText('Страница 1 из 2')
+    fireEvent.click(screen.getByRole('button', { name: 'Скачать PDF' }))
+    expect(api.pdf).toHaveBeenCalledTimes(1)
+    expect(click).toHaveBeenCalledTimes(1)
+    expect(urls).toHaveLength(1)
+    expect(urls[0]).toBe(await vi.mocked(api.pdf).mock.results[0].value)
+    expect(Array.from(new Uint8Array(await urls[0].arrayBuffer()))).toEqual(Array.from(bytes))
+    expect(Array.from(pdf.getDocument.mock.calls[0][0].data as Uint8Array)).toEqual(Array.from(bytes))
+    view.rerender(<PdfPreview consultationId="approved-1" open={false} onClose={vi.fn()} />)
+    expect(revoke).toHaveBeenCalledWith('blob:local-pdf')
+    vi.unstubAllGlobals()
+  })
+
+  it('aborts fetch and never opens a late document after close', async () => {
+    const pending = deferred<Blob>()
+    vi.mocked(api.pdf).mockReturnValue(pending.promise)
+    const { loadingTask } = setupDocument()
+    const view = render(<PdfPreview consultationId="approved-1" open onClose={vi.fn()} />)
+    const signal = vi.mocked(api.pdf).mock.calls[0][1]
+    view.rerender(<PdfPreview consultationId="approved-1" open={false} onClose={vi.fn()} />)
+    expect(signal?.aborted).toBe(true)
+    pending.resolve(new Blob([bytes]))
+    await Promise.resolve()
+    expect(pdf.getDocument).not.toHaveBeenCalled()
+    expect(loadingTask.destroy).not.toHaveBeenCalled()
+  })
+
+  it('destroys a PDF.js loading task if the dialog closes before parsing finishes', async () => {
+    const pending = deferred<ReturnType<typeof setupDocument>['document']>()
+    const { document, loadingTask } = setupDocument()
+    loadingTask.promise = pending.promise
+    const view = render(<PdfPreview consultationId="approved-1" open onClose={vi.fn()} />)
+    await waitFor(() => expect(pdf.getDocument).toHaveBeenCalledTimes(1))
+    view.rerender(<PdfPreview consultationId="approved-1" open={false} onClose={vi.fn()} />)
+    expect(loadingTask.destroy).toHaveBeenCalled()
+    pending.resolve(document)
+    await Promise.resolve()
+    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
+  })
+
+  it('cancels rendering and destroys the old PDF on consultation switch', async () => {
+    const stuck = deferred<void>()
+    const first = setupDocument(stuck.promise)
+    const view = render(<PdfPreview consultationId="approved-1" open onClose={vi.fn()} />)
+    await waitFor(() => expect(first.page.render).toHaveBeenCalledTimes(1))
+    const second = setupDocument()
+    view.rerender(<PdfPreview consultationId="approved-2" open onClose={vi.fn()} />)
+    expect(first.renderTask.cancel).toHaveBeenCalled()
+    expect(first.loadingTask.destroy).toHaveBeenCalled()
+    expect(first.document.cleanup).toHaveBeenCalled()
+    await waitFor(() => expect(second.page.render).toHaveBeenCalledTimes(1))
+    expect(api.pdf).toHaveBeenNthCalledWith(2, 'approved-2', expect.any(AbortSignal))
+    stuck.resolve()
+    await Promise.resolve()
+    expect(first.page.render).toHaveBeenCalledTimes(1)
+    expect(screen.getByText('Страница 1 из 2')).toBeInTheDocument()
+  })
+
+  it('closes with Escape and releases the document on logout unmount', async () => {
+    const first = setupDocument()
+    const onClose = vi.fn()
+    const view = render(<PdfPreview consultationId="approved-1" open onClose={onClose} />)
+    await screen.findByText('Страница 1 из 2')
+    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
+    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
+    view.unmount()
+    expect(first.loadingTask.destroy).toHaveBeenCalled()
+    expect(first.document.cleanup).toHaveBeenCalled()
+  })
+})

```

## package.json
```diff
--- before/package.json
+++ after/package.json
@@ -12,16 +12,17 @@
   "dependencies": {
     "@hookform/resolvers": "^5.2.2",
     "@radix-ui/react-dialog": "^1.1.15",
     "@radix-ui/react-slot": "^1.2.3",
     "@tanstack/react-query": "^5.90.2",
     "class-variance-authority": "^0.7.1",
     "clsx": "^2.1.1",
     "lucide-react": "^0.468.0",
+    "pdfjs-dist": "6.3.289",
     "react": "^19.2.0",
     "react-dom": "^19.2.0",
     "react-hook-form": "^7.64.0",
     "tailwind-merge": "^3.3.1",
     "zod": "^4.1.12"
   },
   "devDependencies": {
     "@testing-library/jest-dom": "^6.9.1",

```

## package-lock.json
```diff
--- before/package-lock.json
+++ after/package-lock.json
@@ -10,16 +10,17 @@
       "dependencies": {
         "@hookform/resolvers": "^5.2.2",
         "@radix-ui/react-dialog": "^1.1.15",
         "@radix-ui/react-slot": "^1.2.3",
         "@tanstack/react-query": "^5.90.2",
         "class-variance-authority": "^0.7.1",
         "clsx": "^2.1.1",
         "lucide-react": "^0.468.0",
+        "pdfjs-dist": "6.3.289",
         "react": "^19.2.0",
         "react-dom": "^19.2.0",
         "react-hook-form": "^7.64.0",
         "tailwind-merge": "^3.3.1",
         "zod": "^4.1.12"
       },
       "devDependencies": {
         "@testing-library/jest-dom": "^6.9.1",
@@ -1166,16 +1167,251 @@
       "integrity": "sha512-zzNR+SdQSDJzc8joaeP8QQoCQr8NuYx2dIIytl1QeBEZHJ9uW6hebsrYgbz8hJwUQao3TWCMtmfV8Nu1twOLAw==",
       "dev": true,
       "license": "MIT",
       "dependencies": {
         "@jridgewell/resolve-uri": "^3.1.0",
         "@jridgewell/sourcemap-codec": "^1.4.14"
       }
     },
+    "node_modules/@napi-rs/canvas": {
+      "version": "1.0.9",
+      "resolved": "https://registry.npmjs.org/@napi-rs/canvas/-/canvas-1.0.9.tgz",
+      "integrity": "sha512-QviPdJImDi/jMAvBfqaw+19BndMd/sizXVW3NnpMd3VJGz++QXkOHcP9kWR/smHG0hNjHeyuHFyrx/5lD0oNcQ==",
+      "optional": true,
+      "engines": {
+        "node": ">= 10"
+      },
+      "funding": {
+        "type": "github",
+        "url": "https://github.com/sponsors/Brooooooklyn"
+      },
+      "optionalDependencies": {
+        "@napi-rs/canvas-android-arm64": "1.0.9",
+        "@napi-rs/canvas-darwin-arm64": "1.0.9",
+        "@napi-rs/canvas-darwin-x64": "1.0.9",
+        "@napi-rs/canvas-linux-arm-gnueabihf": "1.0.9",
+        "@napi-rs/canvas-linux-arm64-gnu": "1.0.9",
+        "@napi-rs/canvas-linux-arm64-musl": "1.0.9",
+        "@napi-rs/canvas-linux-riscv64-gnu": "1.0.9",
+        "@napi-rs/canvas-linux-x64-gnu": "1.0.9",
+        "@napi-rs/canvas-linux-x64-musl": "1.0.9",
+        "@napi-rs/canvas-win32-arm64-msvc": "1.0.9",
+        "@napi-rs/canvas-win32-x64-msvc": "1.0.9"
+      }
+    },
+    "node_modules/@napi-rs/canvas-android-arm64": {
+      "version": "1.0.9",
+      "resolved": "https://registry.npmjs.org/@napi-rs/canvas-android-arm64/-/canvas-android-arm64-1.0.9.tgz",
+      "integrity": "sha512-4LGXk2/0HVzE29K8SzML5WubgCp++B1FH3qgl35XmSZE+lLdr6P9VRQEnZ0MCLZMTSuJP41yyhtoiVNEuvrTIA==",
+      "cpu": [
+        "arm64"
+      ],
+      "optional": true,
+      "os": [
+        "android"
+      ],
+      "engines": {
+        "node": ">= 10"
+      },
+      "funding": {
+        "type": "github",
+        "url": "https://github.com/sponsors/Brooooooklyn"
+      }
+    },
+    "node_modules/@napi-rs/canvas-darwin-arm64": {
+      "version": "1.0.9",
+      "resolved": "https://registry.npmjs.org/@napi-rs/canvas-darwin-arm64/-/canvas-darwin-arm64-1.0.9.tgz",
+      "integrity": "sha512-YNdfLBzY0W/Pep9fo2L6RmoNlNksnn05LRnX66W63R3ij58S25QOTcjdtEt2v8+PnCESzqZsYzUo+QPeIR44NA==",
+      "cpu": [
+        "arm64"
+      ],
+      "optional": true,
+      "os": [
+        "darwin"
+      ],
+      "engines": {
+        "node": ">= 10"
+      },
+      "funding": {
+        "type": "github",
+        "url": "https://github.com/sponsors/Brooooooklyn"
+      }
+    },
+    "node_modules/@napi-rs/canvas-darwin-x64": {
+      "version": "1.0.9",
+      "resolved": "https://registry.npmjs.org/@napi-rs/canvas-darwin-x64/-/canvas-darwin-x64-1.0.9.tgz",
+      "integrity": "sha512-ceZQSknTEcy3dOXoekv59LTCkXjvnLsq+VW5PeNNDHEPQbRS5Ervkm1EaDa7WLAjiYWMLuSQTRTHao1dEX4prg==",
+      "cpu": [
+        "x64"
+      ],
+      "optional": true,
+      "os": [
+        "darwin"
+      ],
+      "engines": {
+        "node": ">= 10"
+      },
+      "funding": {
+        "type": "github",
+        "url": "https://github.com/sponsors/Brooooooklyn"
+      }
+    },
+    "node_modules/@napi-rs/canvas-linux-arm-gnueabihf": {
+      "version": "1.0.9",
+      "resolved": "https://registry.npmjs.org/@napi-rs/canvas-linux-arm-gnueabihf/-/canvas-linux-arm-gnueabihf-1.0.9.tgz",
+      "integrity": "sha512-XhfI0Wwv4llhd6nnWDtY3kQKjq0r+y1i91PlJlJI24ag2U9WrnwbG1qS3+fDLEyouwEVFchiKkTEHozK+5iUNA==",
+      "cpu": [
+        "arm"
+      ],
+      "optional": true,
+      "os": [
+        "linux"
+      ],
+      "engines": {
+        "node": ">= 10"
+      },
+      "funding": {
+        "type": "github",
+        "url": "https://github.com/sponsors/Brooooooklyn"
+      }
+    },
+    "node_modules/@napi-rs/canvas-linux-arm64-gnu": {
+      "version": "1.0.9",
+      "resolved": "https://registry.npmjs.org/@napi-rs/canvas-linux-arm64-gnu/-/canvas-linux-arm64-gnu-1.0.9.tgz",
+      "integrity": "sha512-012oiYtKaE7i9oxc8q7nraT7kDOpLcaCmFLzVe9Ty34RHDdoDzbWLrVh827CNxYh/EADX1eSikA3ymLjo/nNuw==",
+      "cpu": [
+        "arm64"
+      ],
+      "optional": true,
+      "os": [
+        "linux"
+      ],
+      "engines": {
+        "node": ">= 10"
+      },
+      "funding": {
+        "type": "github",
+        "url": "https://github.com/sponsors/Brooooooklyn"
+      }
+    },
+    "node_modules/@napi-rs/canvas-linux-arm64-musl": {
+      "version": "1.0.9",
+      "resolved": "https://registry.npmjs.org/@napi-rs/canvas-linux-arm64-musl/-/canvas-linux-arm64-musl-1.0.9.tgz",
+      "integrity": "sha512-Ls5UWYFFn63casTZEczbeyEg3vRDRkv9lscuGwfchtY5yLLQhgOB8SN4YGxmfJ5vTaBwZ2YUxBS3NtmjJmFXdA==",
+      "cpu": [
+        "arm64"
+      ],
+      "optional": true,
+      "os": [
+        "linux"
+      ],
+      "engines": {
+        "node": ">= 10"
+      },
+      "funding": {
+        "type": "github",
+        "url": "https://github.com/sponsors/Brooooooklyn"
+      }
+    },
+    "node_modules/@napi-rs/canvas-linux-riscv64-gnu": {
+      "version": "1.0.9",
+      "resolved": "https://registry.npmjs.org/@napi-rs/canvas-linux-riscv64-gnu/-/canvas-linux-riscv64-gnu-1.0.9.tgz",
+      "integrity": "sha512-hLKEGxV7ZiRHqndePTokgDMdBlo/rDfzg7P4p4QIv9pUhuYobnu3R2NIFLCRghG0nwfo+s2sw+c1xZFeCmEAsw==",
+      "cpu": [
+        "riscv64"
+      ],
+      "optional": true,
+      "os": [
+        "linux"
+      ],
+      "engines": {
+        "node": ">= 10"
+      },
+      "funding": {
+        "type": "github",
+        "url": "https://github.com/sponsors/Brooooooklyn"
+      }
+    },
+    "node_modules/@napi-rs/canvas-linux-x64-gnu": {
+      "version": "1.0.9",
+      "resolved": "https://registry.npmjs.org/@napi-rs/canvas-linux-x64-gnu/-/canvas-linux-x64-gnu-1.0.9.tgz",
+      "integrity": "sha512-6kaz3w0QMy77PDWk6rJ1ksIihdad3qzEyX2o2oGT8GwCaypfT5mhjr8buOO5hstyLxcWXDScuz56RsINLtBPIQ==",
+      "cpu": [
+        "x64"
+      ],
+      "optional": true,
+      "os": [
+        "linux"
+      ],
+      "engines": {
+        "node": ">= 10"
+      },
+      "funding": {
+        "type": "github",
+        "url": "https://github.com/sponsors/Brooooooklyn"
+      }
+    },
+    "node_modules/@napi-rs/canvas-linux-x64-musl": {
+      "version": "1.0.9",
+      "resolved": "https://registry.npmjs.org/@napi-rs/canvas-linux-x64-musl/-/canvas-linux-x64-musl-1.0.9.tgz",
+      "integrity": "sha512-xrGvmS3v55hmZ86ls/kBLVNMUTYio3f6Ik0DireemG994VfPAwiA3ZXA0Uf1bByctkB3NQ1Sfb+H5bkdUnnzfQ==",
+      "cpu": [
+        "x64"
+      ],
+      "optional": true,
+      "os": [
+        "linux"
+      ],
+      "engines": {
+        "node": ">= 10"
+      },
+      "funding": {
+        "type": "github",
+        "url": "https://github.com/sponsors/Brooooooklyn"
+      }
+    },
+    "node_modules/@napi-rs/canvas-win32-arm64-msvc": {
+      "version": "1.0.9",
+      "resolved": "https://registry.npmjs.org/@napi-rs/canvas-win32-arm64-msvc/-/canvas-win32-arm64-msvc-1.0.9.tgz",
+      "integrity": "sha512-yjmVS3ArZeRVCP7jqbPq4rpZa/BhTeI7ELE2XqJg3snICQBDevLZyArxswHkiTnT34KRic33/4fLirrHI+SY8A==",
+      "cpu": [
+        "arm64"
+      ],
+      "optional": true,
+      "os": [
+        "win32"
+      ],
+      "engines": {
+        "node": ">= 10"
+      },
+      "funding": {
+        "type": "github",
+        "url": "https://github.com/sponsors/Brooooooklyn"
+      }
+    },
+    "node_modules/@napi-rs/canvas-win32-x64-msvc": {
+      "version": "1.0.9",
+      "resolved": "https://registry.npmjs.org/@napi-rs/canvas-win32-x64-msvc/-/canvas-win32-x64-msvc-1.0.9.tgz",
+      "integrity": "sha512-QlSYQdMQslB81nlABo9wNfQ6npFhE7/O+saCZdqVGueGanyRk4jCogD5EwQenfP3kIq9e+mm6GreQBjX5MrA8g==",
+      "cpu": [
+        "x64"
+      ],
+      "optional": true,
+      "os": [
+        "win32"
+      ],
+      "engines": {
+        "node": ">= 10"
+      },
+      "funding": {
+        "type": "github",
+        "url": "https://github.com/sponsors/Brooooooklyn"
+      }
+    },
     "node_modules/@napi-rs/lzma-linux-x64-gnu": {
       "version": "1.5.1",
       "resolved": "https://registry.npmjs.org/@napi-rs/lzma-linux-x64-gnu/-/lzma-linux-x64-gnu-1.5.1.tgz",
       "integrity": "sha512-oTXEIha4SsuXdTA4Iyskj0kpdx2yVXdhd75c2v3xGrHFfVMsbhTPZU/nMPL4sWKo4pBHm3aucLaqGlF696dTyQ==",
       "cpu": [
         "x64"
       ],
       "dev": true,
@@ -3443,16 +3679,27 @@
       "resolved": "https://registry.npmjs.org/pathval/-/pathval-2.0.1.tgz",
       "integrity": "sha512-//nshmD55c46FuFw26xV/xFAaB5HF9Xdap7HJBBnrKdAd6/GxDBaNA1870O79+9ueg61cZLSVc+OaFlfmObYVQ==",
       "dev": true,
       "license": "MIT",
       "engines": {
         "node": ">= 14.16"
       }
     },
+    "node_modules/pdfjs-dist": {
+      "version": "6.3.289",
+      "resolved": "https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-6.3.289.tgz",
+      "integrity": "sha512-ZHjSVpDa3D6izMq8/04lvkhkATUmL9px6ChPaXc1k6nU2Mrhlg1/7F0bdUqCwUjw3NsPTfPZsMDUU6ZIcRaeQw==",
+      "engines": {
+        "node": ">=22.13.0 || >=24"
+      },
+      "optionalDependencies": {
+        "@napi-rs/canvas": "^1.0.0"
+      }
+    },
     "node_modules/picocolors": {
       "version": "1.1.1",
       "resolved": "https://registry.npmjs.org/picocolors/-/picocolors-1.1.1.tgz",
       "integrity": "sha512-xceH2snhtb5M9liqDsmEw56le376mTZkEX/jEb/RxNFyegNul7eNslCXP9FDj/Lcu0X8KEyMceP2ntpaHrDEVA==",
       "dev": true,
       "license": "ISC"
     },
     "node_modules/picomatch": {

```

## deploy/nginx.conf
```diff
--- before/deploy/nginx.conf
+++ after/deploy/nginx.conf
@@ -6,17 +6,17 @@
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

```

## deploy/nginx.tls.conf
```diff
--- before/deploy/nginx.tls.conf
+++ after/deploy/nginx.tls.conf
@@ -16,17 +16,17 @@
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

```

## src/PdfPreview.css
```diff
--- before/src/PdfPreview.css
+++ after/src/PdfPreview.css
@@ -0,0 +1,12 @@
+.pdf-preview-dialog{position:fixed;z-index:80;left:50%;top:50%;transform:translate(-50%,-50%);display:flex;flex-direction:column;width:min(1000px,calc(100vw - 24px));max-height:calc(100dvh - 24px);overflow:hidden;border-radius:18px;background:#fff;box-shadow:0 25px 90px #071e3060}
+.pdf-preview-header,.pdf-preview-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 18px}
+.pdf-preview-header{border-bottom:1px solid #e7efed}
+.pdf-preview-header h2{font-size:18px;font-weight:800;color:#173e46}
+.pdf-preview-header p{font-size:12px;color:#6f858b}
+.pdf-preview-toolbar{flex-wrap:wrap;border-bottom:1px solid #e7efed}
+.pdf-preview-navigation{display:flex;align-items:center;gap:10px;font-size:13px;color:#35535b}
+.pdf-preview-pages{position:relative;min-height:150px;overflow:auto;padding:20px;display:flex;justify-content:center;background:#eaf0ef}
+.pdf-preview-pages canvas{display:block;max-width:100%;height:auto;background:#fff;box-shadow:0 3px 14px #173e4629}
+.pdf-preview-painting{position:absolute;top:30px;background:#fff;padding:8px 12px;border-radius:8px;color:#35535b;font-size:13px}
+.pdf-preview-message{display:flex;min-height:200px;align-items:center;justify-content:center;flex-direction:column;gap:14px;color:#35535b;text-align:center;padding:24px}
+@media(max-width:600px){.pdf-preview-dialog{width:calc(100vw - 12px);max-height:calc(100dvh - 12px)}.pdf-preview-header,.pdf-preview-toolbar{padding:10px}.pdf-preview-navigation{width:100%;justify-content:space-between}.pdf-preview-pages{padding:8px}}

```

