import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, hasToken, setToken } from './api'

beforeEach(() => setToken('test-token'))
afterEach(() => { setToken(null); vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('authenticated file requests', () => {
  it.each(['audio', 'pdf'] as const)('%s sends a bearer header without putting the token in the URL or storing clinical bytes', async method => {
    const storage = vi.spyOn(Storage.prototype, 'setItem')
    const bytes = new Uint8Array([37, 80, 68, 70])
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = new Request(new URL(String(input), 'http://localhost'), init)
      expect(request.headers.get('Authorization')).toBe('Bearer test-token')
      expect(request.url).not.toContain('test-token')
      expect(request.url).toContain(`/consultations/c-1/${method === 'pdf' ? 'document.pdf' : 'audio'}`)
      return new Response(bytes)
    })
    vi.stubGlobal('fetch', fetcher)
    const blob = await api[method]('c-1')
    expect(Array.from(new Uint8Array(await blob.arrayBuffer()))).toEqual(Array.from(bytes))
    expect(fetcher).toHaveBeenCalledOnce()
    expect(storage).not.toHaveBeenCalled()
  })

  it.each(['audio', 'pdf', 'downloadDocx'] as const)('%s shares 401 logout behavior', async method => {
    const unauthorized = vi.fn()
    window.addEventListener('medhub-unauthorized', unauthorized, { once: true })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'Войдите снова' }), { status: 401, headers: { 'Content-Type': 'application/json' } })))
    await expect(api[method]('c-1')).rejects.toMatchObject({ status: 401, message: 'Войдите снова' })
    expect(hasToken()).toBe(false)
    expect(sessionStorage.getItem('medhub.session.token')).toBeNull()
    expect(unauthorized).toHaveBeenCalledOnce()
  })

  it('preserves cancellation instead of reporting a connection error', async () => {
    const controller = new AbortController()
    vi.stubGlobal('fetch', vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    })))
    const pending = api.pdf('c-1', controller.signal)
    controller.abort()
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    expect(hasToken()).toBe(true)
  })

  it('reports AbortError when a canceled fetch rejects with a generic network error', async () => {
    const controller = new AbortController()
    controller.abort()
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    await expect(api.audio('c-1', controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('sends a revision-scoped transcript edit as JSON', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = new Request(new URL(String(input), 'http://localhost'), init)
      expect(request.method).toBe('PATCH')
      expect(request.url).toContain('/consultations/c-1/transcript')
      expect(request.headers.get('Content-Type')).toBe('application/json')
      expect(await request.json()).toEqual({ expected_revision: 2, changes: [{ segment_id: 'seg-000001', text: 'Исправлено' }] })
      return new Response(JSON.stringify({ revision: 3 }), { headers: { 'Content-Type': 'application/json' } })
    }))
    await expect(api.editTranscript('c-1', 2, [{ segment_id: 'seg-000001', text: 'Исправлено' }])).resolves.toMatchObject({ revision: 3 })
  })

  it('uses a safe error when a file response is not JSON', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('proxy failure', { status: 502 })))
    await expect(api.pdf('c-1')).rejects.toBeInstanceOf(ApiError)
    await expect(api.pdf('c-1')).rejects.toMatchObject({ status: 502 })
  })

  it('retains the DOCX-specific connection message', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    await expect(api.downloadDocx('c-1')).rejects.toMatchObject({
      status: 0, message: 'Не удалось скачать документ. Проверьте соединение.',
    })
  })
})

describe('public verification', () => {
  it('fetches the opaque verification ID without sending a session token', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = new Request(new URL(String(input), 'http://localhost'), init)
      expect(request.url).toBe('http://localhost/api/v1/verification/opaque-123')
      expect(request.headers.has('Authorization')).toBe(false)
      return new Response(JSON.stringify({ issuer: 'MedHub', issued_at: '2026-09-30T00:00:00Z', status: 'valid', sha256: 'a'.repeat(64) }), { headers: { 'Content-Type': 'application/json' } })
    }))
    await expect(api.verification('opaque-123')).resolves.toMatchObject({ issuer: 'MedHub', status: 'valid' })
  })
})

describe('protocol lookup', () => {
  it('sends only the physician search term, never clinical data', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = new Request(new URL(String(input), 'http://localhost'), init)
      expect(request.url).toBe('http://localhost/api/v1/protocols/search')
      expect(request.headers.get('Authorization')).toBe('Bearer test-token')
      expect(await request.json()).toEqual({ query: 'артериальная гипертензия', limit: 10 })
      return new Response(JSON.stringify({ items: [] }), { headers: { 'Content-Type': 'application/json' } })
    }))
    await expect(api.searchProtocols('артериальная гипертензия')).resolves.toEqual({ items: [] })
  })
})
