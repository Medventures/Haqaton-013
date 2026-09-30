import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'
import { PdfPreview } from './PdfPreview'

const pdf = vi.hoisted(() => ({ getDocument: vi.fn() }))
vi.mock('pdfjs-dist', () => ({ getDocument: pdf.getDocument, GlobalWorkerOptions: { workerSrc: '' } }))
vi.mock('./api', () => ({ api: { pdf: vi.fn() } }))

const bytes = new Uint8Array([37, 80, 68, 70, 45, 49, 46, 55])
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

function setupDocument(renderPromise: Promise<void> = Promise.resolve()) {
  const renderTask = { promise: renderPromise, cancel: vi.fn() }
  const page = { getViewport: vi.fn(({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale })), render: vi.fn(() => renderTask) }
  const document = { numPages: 2, getPage: vi.fn(async () => page), cleanup: vi.fn((): Promise<void> => Promise.resolve()) }
  const loadingTask = { promise: Promise.resolve(document), destroy: vi.fn((): Promise<void> => Promise.resolve()) }
  pdf.getDocument.mockReturnValue(loadingTask)
  return { renderTask, page, document, loadingTask }
}

beforeEach(() => {
  vi.clearAllMocks()
  Object.defineProperty(Blob.prototype, 'arrayBuffer', { configurable: true, value: async () => bytes.buffer.slice(0) })
  vi.mocked(api.pdf).mockResolvedValue(new Blob([bytes], { type: 'application/pdf' }))
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as CanvasRenderingContext2D)
})
afterEach(() => { cleanup(); Reflect.deleteProperty(Blob.prototype, 'arrayBuffer'); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('authenticated PDF preview', () => {
  it('loads once per opening and navigates rendered pages', async () => {
    const { document, page } = setupDocument()
    const view = render(<PdfPreview consultationId="approved-1" open={false} onClose={vi.fn()} />)
    expect(api.pdf).not.toHaveBeenCalled()
    view.rerender(<PdfPreview consultationId="approved-1" open onClose={vi.fn()} />)
    await waitFor(() => expect(page.render).toHaveBeenCalledTimes(1))
    expect(api.pdf).toHaveBeenCalledTimes(1)
    expect(document.getPage).toHaveBeenCalledWith(1)
    expect(screen.getByText('Страница 1 из 2')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Предыдущая страница' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Следующая страница' }))
    await waitFor(() => expect(document.getPage).toHaveBeenCalledWith(2))
    expect(screen.getByText('Страница 2 из 2')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Следующая страница' })).toBeDisabled()
  })

  it('shows an error and retries with a fresh authenticated request', async () => {
    setupDocument()
    vi.mocked(api.pdf).mockRejectedValueOnce(new Error('network'))
    render(<PdfPreview consultationId="approved-1" open onClose={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось загрузить PDF')
    expect(pdf.getDocument).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    await waitFor(() => expect(screen.getByText('Страница 1 из 2')).toBeInTheDocument())
    expect(api.pdf).toHaveBeenCalledTimes(2)
  })

  it('downloads the same fetched Blob without a second PDF request', async () => {
    setupDocument()
    const urls: Blob[] = []
    const revoke = vi.fn()
    vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn((blob: Blob) => { urls.push(blob); return 'blob:local-pdf' }), revokeObjectURL: revoke })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const view = render(<PdfPreview consultationId="approved-1" open onClose={vi.fn()} />)
    await screen.findByText('Страница 1 из 2')
    fireEvent.click(screen.getByRole('button', { name: 'Скачать PDF' }))
    expect(api.pdf).toHaveBeenCalledTimes(1)
    expect(click).toHaveBeenCalledTimes(1)
    expect(urls).toHaveLength(1)
    expect(urls[0]).toBe(await vi.mocked(api.pdf).mock.results[0].value)
    expect(Array.from(new Uint8Array(await urls[0].arrayBuffer()))).toEqual(Array.from(bytes))
    expect(Array.from(pdf.getDocument.mock.calls[0][0].data as Uint8Array)).toEqual(Array.from(bytes))
    view.rerender(<PdfPreview consultationId="approved-1" open={false} onClose={vi.fn()} />)
    expect(revoke).toHaveBeenCalledWith('blob:local-pdf')
    vi.unstubAllGlobals()
  })

  it('aborts fetch and never opens a late document after close', async () => {
    const pending = deferred<Blob>()
    vi.mocked(api.pdf).mockReturnValue(pending.promise)
    const { loadingTask } = setupDocument()
    const view = render(<PdfPreview consultationId="approved-1" open onClose={vi.fn()} />)
    const signal = vi.mocked(api.pdf).mock.calls[0][1]
    view.rerender(<PdfPreview consultationId="approved-1" open={false} onClose={vi.fn()} />)
    expect(signal?.aborted).toBe(true)
    pending.resolve(new Blob([bytes]))
    await Promise.resolve()
    expect(pdf.getDocument).not.toHaveBeenCalled()
    expect(loadingTask.destroy).not.toHaveBeenCalled()
  })

  it('destroys a PDF.js loading task if the dialog closes before parsing finishes', async () => {
    const pending = deferred<ReturnType<typeof setupDocument>['document']>()
    const { document, loadingTask } = setupDocument()
    loadingTask.promise = pending.promise
    const view = render(<PdfPreview consultationId="approved-1" open onClose={vi.fn()} />)
    await waitFor(() => expect(pdf.getDocument).toHaveBeenCalledTimes(1))
    view.rerender(<PdfPreview consultationId="approved-1" open={false} onClose={vi.fn()} />)
    expect(loadingTask.destroy).toHaveBeenCalled()
    pending.resolve(document)
    await Promise.resolve()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('cancels rendering and destroys the old PDF on consultation switch', async () => {
    const stuck = deferred<void>()
    const first = setupDocument(stuck.promise)
    const view = render(<PdfPreview consultationId="approved-1" open onClose={vi.fn()} />)
    await waitFor(() => expect(first.page.render).toHaveBeenCalledTimes(1))
    const second = setupDocument()
    view.rerender(<PdfPreview consultationId="approved-2" open onClose={vi.fn()} />)
    expect(first.renderTask.cancel).toHaveBeenCalled()
    expect(first.loadingTask.destroy).toHaveBeenCalled()
    await waitFor(() => expect(first.document.cleanup).toHaveBeenCalled())
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
    await waitFor(() => expect(first.document.cleanup).toHaveBeenCalled())
  })

  it('waits for worker destruction before cleaning up a rendering document', async () => {
    const rendering = deferred<void>()
    const destroying = deferred<void>()
    const first = setupDocument(rendering.promise)
    first.loadingTask.destroy.mockReturnValue(destroying.promise)
    const view = render(<PdfPreview consultationId="approved-1" open onClose={vi.fn()} />)
    await waitFor(() => expect(first.page.render).toHaveBeenCalledTimes(1))
    view.unmount()
    expect(first.renderTask.cancel).toHaveBeenCalled()
    expect(first.loadingTask.destroy).toHaveBeenCalled()
    expect(first.document.cleanup).not.toHaveBeenCalled()
    destroying.resolve()
    await waitFor(() => expect(first.document.cleanup).toHaveBeenCalled())
  })
})
