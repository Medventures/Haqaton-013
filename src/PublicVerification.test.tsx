import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import App from './App'
import { setToken } from './api'

beforeEach(() => { setToken(null); window.history.replaceState(null, '', '/verify/opaque-123') })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); window.history.replaceState(null, '', '/') })

it('shows only public verification metadata without login and hashes a selected PDF locally', async () => {
  const requests: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = new Request(new URL(String(input), 'http://localhost'), init)
    requests.push(request.url)
    expect(request.method).toBe('GET')
    expect(request.url).toBe('http://localhost/api/v1/verification/opaque-123')
    return new Response(JSON.stringify({ issuer: 'MedHub', issued_at: '2026-09-30T00:00:00Z', status: 'valid', sha256: '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08' }), { headers: { 'Content-Type': 'application/json' } })
  }))
  render(<App />)
  expect(await screen.findByText(/Запись PDF действительна/)).toBeVisible()
  expect(screen.getByText('MedHub')).toBeVisible()
  expect(screen.queryByText('Вход в MedHub')).not.toBeInTheDocument()
  const file = new File(['test'], 'synthetic.pdf', { type: 'application/pdf' })
  Object.defineProperty(file, 'arrayBuffer', { value: async () => new TextEncoder().encode('test').buffer })
  fireEvent.change(screen.getByLabelText(/Проверить файл PDF/), { target: { files: [file] } })
  expect(await screen.findByText(/Выбранный PDF совпадает/)).toBeVisible()
  expect(requests).toEqual(['http://localhost/api/v1/verification/opaque-123'])
})
