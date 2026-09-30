import { useEffect, useRef, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { Download, X } from 'lucide-react'
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
import type { PDFDocumentLoadingTask, PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { api } from './api'
import { Button } from './ui'
import './PdfPreview.css'

GlobalWorkerOptions.workerSrc = workerUrl

type Ready = { kind: 'ready'; blob: Blob; document: PDFDocumentProxy }
type PreviewState = { kind: 'loading' } | { kind: 'error' } | Ready

export function PdfPreview({ consultationId, open, onClose }: { consultationId: string; open: boolean; onClose: () => void }) {
  return open ? <PreviewSession key={consultationId} consultationId={consultationId} onClose={onClose} /> : null
}

function PreviewSession({ consultationId, onClose }: { consultationId: string; onClose: () => void }) {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<PreviewState>({ kind: 'loading' })
  const [pageNumber, setPageNumber] = useState(1)
  const [pageWidth, setPageWidth] = useState(720)
  const [painted, setPainted] = useState(false)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const pageBoxRef = useRef<HTMLDivElement>(null)
  const renderTaskRef = useRef<RenderTask | null>(null)
  const downloadUrls = useRef(new Set<string>())
  const revokeTimers = useRef(new Set<ReturnType<typeof setTimeout>>())

  useEffect(() => {
    let active = true
    const controller = new AbortController()
    let loadingTask: PDFDocumentLoadingTask | null = null
    let pdfDocument: PDFDocumentProxy | null = null
    setState({ kind: 'loading' })
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
        if (!active) { void document.cleanup().catch(() => {}); return }
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
      if (loadingTask) {
        void loadingTask.destroy().catch(() => {}).then(() => pdfDocument?.cleanup()).catch(() => {})
      } else if (pdfDocument) {
        void pdfDocument.cleanup().catch(() => {})
      }
    }
  }, [consultationId, attempt])

  useEffect(() => {
    const box = pageBoxRef.current
    if (!box || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(entries => {
      const width = Math.floor(entries[0]?.contentRect.width ?? 0)
      if (width > 0) setPageWidth(width)
    })
    observer.observe(box)
    return () => observer.disconnect()
  }, [state.kind])

  useEffect(() => {
    if (state.kind !== 'ready') return
    const activeDocument = state.document
    let active = true
    let renderTask: RenderTask | null = null
    setPainted(false)
    async function paint() {
      try {
        const page = await activeDocument.getPage(pageNumber)
        if (!active) return
        const canvas = canvasRef.current
        const context = canvas?.getContext('2d')
        if (!canvas || !context) throw new Error('Canvas unavailable')
        const base = page.getViewport({ scale: 1 })
        const scale = Math.min(pageWidth, 900) / base.width
        const cssViewport = page.getViewport({ scale })
        const viewport = page.getViewport({ scale: scale * (window.devicePixelRatio || 1) })
        canvas.width = Math.ceil(viewport.width)
        canvas.height = Math.ceil(viewport.height)
        canvas.style.width = `${Math.ceil(cssViewport.width)}px`
        const task = page.render({ canvas, canvasContext: context, viewport })
        renderTask = task
        renderTaskRef.current = task
        await task.promise
        if (active) setPainted(true)
      } catch {
        if (active) setState({ kind: 'error' })
      }
    }
    void paint()
    return () => {
      active = false
      renderTask?.cancel()
      if (renderTaskRef.current === renderTask) renderTaskRef.current = null
    }
  }, [state, pageNumber, pageWidth])

  useEffect(() => () => {
    for (const timer of revokeTimers.current) clearTimeout(timer)
    for (const url of downloadUrls.current) URL.revokeObjectURL(url)
    revokeTimers.current.clear()
    downloadUrls.current.clear()
  }, [])

  function download() {
    if (state.kind !== 'ready') return
    const url = URL.createObjectURL(state.blob)
    downloadUrls.current.add(url)
    const anchor = window.document.createElement('a')
    anchor.href = url
    anchor.download = `consultation-${consultationId}.pdf`
    window.document.body.append(anchor)
    anchor.click()
    anchor.remove()
    const timer = window.setTimeout(() => {
      URL.revokeObjectURL(url)
      downloadUrls.current.delete(url)
      revokeTimers.current.delete(timer)
    }, 30_000)
    revokeTimers.current.add(timer)
  }

  return <Dialog.Root open onOpenChange={next => { if (!next) onClose() }}>
    <Dialog.Portal>
      <Dialog.Overlay className="dialog-overlay" />
      <Dialog.Content className="pdf-preview-dialog" aria-describedby="pdf-preview-description">
        <header className="pdf-preview-header">
          <div><Dialog.Title>Просмотр PDF</Dialog.Title><Dialog.Description id="pdf-preview-description">Подтверждённый документ консультации</Dialog.Description></div>
          <Dialog.Close asChild><Button variant="ghost" size="icon" aria-label="Закрыть просмотр"><X size={18} /></Button></Dialog.Close>
        </header>
        {state.kind === 'loading' && <div className="pdf-preview-message" role="status">Загружаем PDF…</div>}
        {state.kind === 'error' && <div className="pdf-preview-message"><p role="alert">Не удалось загрузить PDF.</p><Button onClick={() => setAttempt(value => value + 1)}>Повторить</Button></div>}
        {state.kind === 'ready' && <>
          <div className="pdf-preview-toolbar">
            <div className="pdf-preview-navigation">
              <Button variant="secondary" size="sm" aria-label="Предыдущая страница" disabled={pageNumber === 1} onClick={() => setPageNumber(value => value - 1)}>Назад</Button>
              <span aria-live="polite">Страница {pageNumber} из {state.document.numPages}</span>
              <Button variant="secondary" size="sm" aria-label="Следующая страница" disabled={pageNumber === state.document.numPages} onClick={() => setPageNumber(value => value + 1)}>Вперёд</Button>
            </div>
            <Button size="sm" onClick={download}><Download size={16} /> Скачать PDF</Button>
          </div>
          <div className="pdf-preview-pages" ref={pageBoxRef}>
            {!painted && <span className="pdf-preview-painting" role="status">Рисуем страницу…</span>}
            <canvas key={pageNumber} ref={canvasRef} aria-label={`Страница ${pageNumber} PDF`} />
          </div>
        </>}
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>
}
