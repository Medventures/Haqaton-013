import type { AuditEntry, ClinicalData, ClinicalProtocol, Consultation, ConsultationTemplate, Document, ExportResult, Health, ProtocolCandidate, PublicVerification, Transcript, TranscriptTextChange, User } from './types'

const BASE = '/api/v1'
const TOKEN_KEY = 'medhub.session.token'
let token = sessionStorage.getItem(TOKEN_KEY)

export function setToken(value: string | null) {
  token = value
  if (value) sessionStorage.setItem(TOKEN_KEY, value)
  else sessionStorage.removeItem(TOKEN_KEY)
}
export function hasToken() { return Boolean(token) }

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); this.name = 'ApiError' }
}

async function responseFor(path: string, options: RequestInit = {}, fallback = 'Не удалось выполнить действие. Попробуйте ещё раз.', connectionFallback = 'Не удалось связаться с сервером. Проверьте соединение.', includeAuth = true): Promise<Response> {
  const headers = new Headers(options.headers)
  if (includeAuth && token) headers.set('Authorization', `Bearer ${token}`)
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  let response: Response
  try { response = await fetch(`${BASE}${path}`, { ...options, headers }) }
  catch (cause) {
    if (options.signal?.aborted) throw new DOMException('The operation was aborted.', 'AbortError')
    if (cause instanceof Error && cause.name === 'AbortError') throw cause
    throw new ApiError(connectionFallback, 0)
  }
  if (!response.ok) {
    let message = fallback
    try {
      const body = await response.json() as { detail?: string | unknown }
      if (typeof body.detail === 'string') message = body.detail
    } catch { /* use safe generic message */ }
    if (includeAuth && response.status === 401 && token) { setToken(null); window.dispatchEvent(new Event('medhub-unauthorized')) }
    throw new ApiError(message, response.status)
  }
  return response
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  return (await responseFor(path, options)).json() as Promise<T>
}

async function publicRequest<T>(path: string): Promise<T> {
  return (await responseFor(path, {}, undefined, undefined, false)).json() as Promise<T>
}

async function binary(path: string, signal?: AbortSignal, fallback = 'Не удалось загрузить файл.', connectionFallback?: string): Promise<Blob> {
  return (await responseFor(path, { signal }, fallback, connectionFallback)).blob()
}

const json = (body: unknown) => JSON.stringify(body)
export const api = {
  health: () => request<Health>('/health'),
  verification: (id: string) => publicRequest<PublicVerification>(`/verification/${encodeURIComponent(id)}`),
  searchProtocols: (query: string) => request<{ items: ProtocolCandidate[] }>('/protocols/search', { method: 'POST', body: json({ query, limit: 10 }) }),
  protocol: (id: string) => request<ClinicalProtocol>(`/protocols/${encodeURIComponent(id)}`),
  login: (username: string, password: string) => request<{ access_token: string; token_type: 'bearer'; user: User }>('/auth/login', { method: 'POST', body: json({ username, password }) }),
  me: () => request<User>('/auth/me'),
  templates: () => request<ConsultationTemplate[]>('/templates'),
  diagnoses: (q: string) => request<{ items: { code: string; name_ru: string; name_kz: string | null }[]; total: number }>(`/diagnoses?q=${encodeURIComponent(q)}&limit=20`),
  consultations: () => request<Consultation[]>('/consultations'),
  create: (external_patient_id: string, template_id: string) => request<Consultation>('/consultations', { method: 'POST', body: json({ external_patient_id, template_id }) }),
  consultation: (id: string) => request<Consultation>(`/consultations/${id}`),
  beginRecording: (id: string) => request<Consultation>(`/consultations/${id}/recording`, { method: 'POST' }),
  upload: (id: string, file: File) => {
    const body = new FormData(); body.append('file', file)
    return request<Consultation>(`/consultations/${id}/audio`, { method: 'POST', body })
  },
  transcribe: (id: string) => request<Transcript>(`/consultations/${id}/transcribe`, { method: 'POST' }),
  demo: (id: string) => request<Transcript>(`/consultations/${id}/demo`, { method: 'POST' }),
  transcript: (id: string) => request<Transcript>(`/consultations/${id}/transcript`),
  editTranscript: (id: string, expected_revision: number, changes: TranscriptTextChange[]) => request<Transcript>(`/consultations/${encodeURIComponent(id)}/transcript`, { method: 'PATCH', body: json({ expected_revision, changes }) }),
  audio: (id: string, signal?: AbortSignal) => binary(`/consultations/${encodeURIComponent(id)}/audio`, signal),
  pdf: (id: string, signal?: AbortSignal) => binary(`/consultations/${encodeURIComponent(id)}/document.pdf`, signal),
  generate: (id: string) => request<Document>(`/consultations/${id}/generate`, { method: 'POST' }),
  document: (id: string) => request<Document>(`/consultations/${id}/document`),
  save: (id: string, data: ClinicalData, version: number) => request<Document>(`/consultations/${id}/document`, { method: 'PATCH', body: json({ data, version }) }),
  approve: (id: string, version: number) => request<Consultation>(`/consultations/${id}/approve`, { method: 'POST', body: json({ version }) }),
  sendToMis: (id: string) => request<ExportResult>(`/consultations/${id}/send-to-mis`, { method: 'POST' }),
  audit: (id: string) => request<AuditEntry[]>(`/consultations/${id}/audit`),
  async downloadDocx(id: string) {
    const blob = await binary(`/consultations/${encodeURIComponent(id)}/document.docx`, undefined, 'Не удалось скачать документ.', 'Не удалось скачать документ. Проверьте соединение.')
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `consultation-${id}.docx`
    document.body.append(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  },
}
