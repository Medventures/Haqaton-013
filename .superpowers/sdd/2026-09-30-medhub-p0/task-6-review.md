# Task6 review package

Diff against immediate task baseline outside project. New components/tests against /dev/null.

## src/types.ts
```diff
--- before/src/types.ts
+++ after/src/types.ts
@@ -1,17 +1,25 @@
 export type Status = 'CREATED' | 'RECORDING' | 'PROCESSING' | 'TRANSCRIBED' | 'AI_GENERATED' | 'REVIEWED' | 'APPROVED' | 'SENT_TO_MIS' | 'FAILED'
 
 export interface User { id: string; username: string; role: 'doctor' | 'admin'; display_name: string }
 export interface Health { status: 'ok'; mode: 'demo' | 'live'; stt_model: string; llm_provider: 'demo' | 'openai'; llm_model: string; mis_provider: 'mock' }
 export interface TemplateField { key: string; label: string; prompt: string; section: string; clinical_field?: string | null }
 export interface ConsultationTemplate { id: string; name: string; fields: TemplateField[] }
-export interface Consultation { id: string; external_patient_id: string; template_id: string; status: Status; created_at: string; updated_at: string; approved_at: string | null; error_message: string | null }
-export interface TranscriptSegment { start: number; end: number; text: string; speaker: string | null }
-export interface Transcript { raw_text: string; normalized_text: string; masked_text: string; language: string; duration_seconds: number; stt_model: string; segments: TranscriptSegment[]; pii_entities: { type: string; placeholder: string }[] }
+export type ProcessingOperation = 'upload' | 'transcribe' | 'generate'
+export type ProcessingStatus = 'running' | 'done' | 'error'
+export type StageStatus = 'pending' | ProcessingStatus
+export type ProcessingErrorCode = 'UPLOAD_FAILED' | 'STT_FAILED' | 'NORMALIZATION_FAILED' | 'MASKING_FAILED' | 'LLM_FAILED' | 'VALIDATION_FAILED' | 'INTERRUPTED'
+export interface ProcessingStage { key: string; attempt: number; status: StageStatus; started_at: string | null; finished_at: string | null; duration_ms: number | null; error_code: ProcessingErrorCode | null }
+export interface ProcessingRun { id: string; operation: ProcessingOperation; status: ProcessingStatus; started_at: string; finished_at: string | null; stages: ProcessingStage[] }
+export interface Consultation { id: string; external_patient_id: string; template_id: string; status: Status; created_at: string; updated_at: string; approved_at: string | null; error_message: string | null; transcript_revision: number | null; audio_available: boolean; processing_runs: ProcessingRun[] }
+export interface TranscriptSegment { id: string; start: number; end: number; text: string; speaker: string | null }
+export interface TranscriptTextChange { segment_id: string; text: string }
+export interface PIIEntity { type: string; placeholder: string }
+export interface Transcript { raw_text: string; normalized_text: string; masked_text: string; current_text: string; revision: number; audio_available: boolean; language: string; duration_seconds: number; stt_model: string; segments: TranscriptSegment[]; pii_entities: PIIEntity[] }
 export interface Medication { name: string; dosage: string | null; frequency: string | null; duration: string | null }
 export interface VitalSigns { temperature: string | null; blood_pressure: string | null; heart_rate: string | null; respiratory_rate: string | null; oxygen_saturation: string | null }
 export interface ClinicalData {
   complaints: string[]
   anamnesis_morbi: string | null
   anamnesis_vitae: string | null
   allergies: string[]
   medications: Medication[]
@@ -19,11 +27,12 @@
   objective_status: string | null
   diagnosis: string | null
   diagnosis_code: string | null
   recommendations: string[]
   prescribed_medications: Medication[]
   additional_notes: string | null
   template_fields: { key: string; value: string | null }[]
 }
-export interface Document { id: string; consultation_id: string; ai_generated_data: ClinicalData; doctor_approved_data: ClinicalData | null; data: ClinicalData; llm_provider: string; llm_model: string; updated_at: string; version: number }
+export interface EvidenceLink { field_path: string; segment_id: string; quote: string; transcript_revision: number; start: number; end: number }
+export interface Document { id: string; consultation_id: string; ai_generated_data: ClinicalData; doctor_approved_data: ClinicalData | null; data: ClinicalData; llm_provider: string; llm_model: string; updated_at: string; version: number; source_transcript_revision: number | null; source_masked_text: string | null; evidence: EvidenceLink[] }
 export interface AuditEntry { id: string; field: string; ai_value: unknown; doctor_value: unknown; changed: boolean; created_at: string }
 export interface ExportResult { success: boolean; document_id: string; provider: 'mock' }

```

## src/api.ts
```diff
--- before/src/api.ts
+++ after/src/api.ts
@@ -1,42 +1,54 @@
-import type { AuditEntry, ClinicalData, Consultation, ConsultationTemplate, Document, ExportResult, Health, Transcript, User } from './types'
+import type { AuditEntry, ClinicalData, Consultation, ConsultationTemplate, Document, ExportResult, Health, Transcript, TranscriptTextChange, User } from './types'
 
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
 
-async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
+async function responseFor(path: string, options: RequestInit = {}, fallback = 'Не удалось выполнить действие. Попробуйте ещё раз.', connectionFallback = 'Не удалось связаться с сервером. Проверьте соединение.'): Promise<Response> {
   const headers = new Headers(options.headers)
   if (token) headers.set('Authorization', `Bearer ${token}`)
   if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
   let response: Response
   try { response = await fetch(`${BASE}${path}`, { ...options, headers }) }
-  catch { throw new ApiError('Не удалось связаться с сервером. Проверьте соединение.', 0) }
+  catch (cause) {
+    if (options.signal?.aborted) throw new DOMException('The operation was aborted.', 'AbortError')
+    if (cause instanceof Error && cause.name === 'AbortError') throw cause
+    throw new ApiError(connectionFallback, 0)
+  }
   if (!response.ok) {
-    let message = 'Не удалось выполнить действие. Попробуйте ещё раз.'
+    let message = fallback
     try {
       const body = await response.json() as { detail?: string | unknown }
       if (typeof body.detail === 'string') message = body.detail
     } catch { /* use safe generic message */ }
     if (response.status === 401 && token) { setToken(null); window.dispatchEvent(new Event('medhub-unauthorized')) }
     throw new ApiError(message, response.status)
   }
-  return response.json() as Promise<T>
+  return response
+}
+
+async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
+  return (await responseFor(path, options)).json() as Promise<T>
+}
+
+async function binary(path: string, signal?: AbortSignal, fallback = 'Не удалось загрузить файл.', connectionFallback?: string): Promise<Blob> {
+  return (await responseFor(path, { signal }, fallback, connectionFallback)).blob()
 }
 
 const json = (body: unknown) => JSON.stringify(body)
 export const api = {
   health: () => request<Health>('/health'),
   login: (username: string, password: string) => request<{ access_token: string; token_type: 'bearer'; user: User }>('/auth/login', { method: 'POST', body: json({ username, password }) }),
   me: () => request<User>('/auth/me'),
   templates: () => request<ConsultationTemplate[]>('/templates'),
@@ -47,32 +59,27 @@
   beginRecording: (id: string) => request<Consultation>(`/consultations/${id}/recording`, { method: 'POST' }),
   upload: (id: string, file: File) => {
     const body = new FormData(); body.append('file', file)
     return request<Consultation>(`/consultations/${id}/audio`, { method: 'POST', body })
   },
   transcribe: (id: string) => request<Transcript>(`/consultations/${id}/transcribe`, { method: 'POST' }),
   demo: (id: string) => request<Transcript>(`/consultations/${id}/demo`, { method: 'POST' }),
   transcript: (id: string) => request<Transcript>(`/consultations/${id}/transcript`),
+  editTranscript: (id: string, expected_revision: number, changes: TranscriptTextChange[]) => request<Transcript>(`/consultations/${encodeURIComponent(id)}/transcript`, { method: 'PATCH', body: json({ expected_revision, changes }) }),
+  audio: (id: string, signal?: AbortSignal) => binary(`/consultations/${encodeURIComponent(id)}/audio`, signal),
+  pdf: (id: string, signal?: AbortSignal) => binary(`/consultations/${encodeURIComponent(id)}/document.pdf`, signal),
   generate: (id: string) => request<Document>(`/consultations/${id}/generate`, { method: 'POST' }),
   document: (id: string) => request<Document>(`/consultations/${id}/document`),
   save: (id: string, data: ClinicalData, version: number) => request<Document>(`/consultations/${id}/document`, { method: 'PATCH', body: json({ data, version }) }),
   approve: (id: string, version: number) => request<Consultation>(`/consultations/${id}/approve`, { method: 'POST', body: json({ version }) }),
   sendToMis: (id: string) => request<ExportResult>(`/consultations/${id}/send-to-mis`, { method: 'POST' }),
   audit: (id: string) => request<AuditEntry[]>(`/consultations/${id}/audit`),
   async downloadDocx(id: string) {
-    let response: Response
-    try { response = await fetch(`${BASE}/consultations/${id}/document.docx`, { headers: { Authorization: `Bearer ${token}` } }) }
-    catch { throw new ApiError('Не удалось скачать документ. Проверьте соединение.', 0) }
-    if (!response.ok) {
-      let message = 'Не удалось скачать документ.'
-      try { const body = await response.json() as { detail?: unknown }; if (typeof body.detail === 'string') message = body.detail } catch { /* safe generic message */ }
-      throw new ApiError(message, response.status)
-    }
-    const blob = await response.blob()
+    const blob = await binary(`/consultations/${encodeURIComponent(id)}/document.docx`, undefined, 'Не удалось скачать документ.', 'Не удалось скачать документ. Проверьте соединение.')
     const url = URL.createObjectURL(blob)
     const anchor = document.createElement('a')
     anchor.href = url
     anchor.download = `consultation-${id}.docx`
     document.body.append(anchor)
     anchor.click()
     anchor.remove()
     window.setTimeout(() => URL.revokeObjectURL(url), 60_000)

```

## src/ProcessingPanel.tsx
```diff
--- before/src/ProcessingPanel.tsx
+++ after/src/ProcessingPanel.tsx
@@ -0,0 +1,66 @@
+import { useEffect, useState } from 'react'
+import type { ProcessingErrorCode, ProcessingRun, ProcessingStage } from './types'
+
+const operationNames: Record<ProcessingRun['operation'], string> = {
+  upload: 'Загрузка аудио', transcribe: 'Транскрипция', generate: 'Подготовка черновика',
+}
+const stageNames: Record<string, string> = {
+  upload: 'Загрузка файла', stt: 'Распознавание речи', normalization: 'Нормализация текста',
+  pii_masking: 'Маскирование персональных данных', llm_extraction: 'Извлечение данных',
+  output_validation: 'Проверка результата',
+}
+const failureNames: Record<ProcessingErrorCode, string> = {
+  UPLOAD_FAILED: 'Ошибка загрузки', STT_FAILED: 'Ошибка распознавания',
+  NORMALIZATION_FAILED: 'Ошибка нормализации', MASKING_FAILED: 'Ошибка маскирования',
+  LLM_FAILED: 'Ошибка извлечения данных', VALIDATION_FAILED: 'Ошибка проверки результата',
+  INTERRUPTED: 'Обработка прервана',
+}
+
+function seconds(milliseconds: number): string {
+  return `${(milliseconds / 1000).toFixed(1).replace('.', ',')} с`
+}
+
+function duration(stage: ProcessingStage, now: number, running: boolean): string | null {
+  if (stage.status === 'pending') return null
+  if (stage.status === 'running' && running && stage.started_at) {
+    const started = Date.parse(stage.started_at)
+    return Number.isFinite(started) ? seconds(Math.max(0, now - started)) : null
+  }
+  return stage.duration_ms === null ? null : seconds(stage.duration_ms)
+}
+
+function statusText(stage: ProcessingStage): string {
+  if (stage.status === 'pending') return 'Ожидает'
+  if (stage.status === 'running') return 'Выполняется'
+  if (stage.status === 'done') return 'Завершено'
+  return stage.error_code ? failureNames[stage.error_code] ?? 'Этап завершился с ошибкой' : 'Этап завершился с ошибкой'
+}
+
+export function ProcessingPanel({ runs }: { runs: ProcessingRun[] }) {
+  const [now, setNow] = useState(() => Date.now())
+  const hasRunningStage = runs.some(run => run.status === 'running' && run.stages.some(stage => stage.status === 'running' && stage.started_at))
+  useEffect(() => {
+    if (!hasRunningStage) return
+    setNow(Date.now())
+    const timer = window.setInterval(() => setNow(Date.now()), 1000)
+    return () => window.clearInterval(timer)
+  }, [hasRunningStage])
+
+  return <section aria-labelledby="processing-heading" className="processing-panel">
+    <h2 id="processing-heading">Ход обработки</h2>
+    {runs.length === 0 ? <p>История обработки недоступна. Длительность неизвестна.</p> :
+      runs.map(run => <div key={run.id} className="processing-run">
+        <h3>{operationNames[run.operation]} — {run.status === 'running' ? 'Выполняется' : run.status === 'done' ? 'Завершено' : 'Ошибка'}</h3>
+        {run.stages.length === 0 ? <p>Сведения об этапах отсутствуют. Длительность неизвестна.</p> :
+          <ol className="processing-stages">{run.stages.map((stage, index) => {
+            const elapsed = duration(stage, now, run.status === 'running')
+            return <li key={`${stage.key}-${stage.attempt}-${index}`}>
+              <span>{stageNames[stage.key] ?? stage.key}{stage.attempt > 1 ? ` · попытка ${stage.attempt}` : ''}</span>
+              <span>{statusText(stage)}</span>
+              {elapsed && <span aria-label={`Длительность: ${elapsed}`}>{elapsed}</span>}
+              {stage.status !== 'pending' && !elapsed && <span>Длительность неизвестна</span>}
+            </li>
+          })}</ol>}
+      </div>)}
+  </section>
+}

```

## src/ProcessingPanel.test.tsx
```diff
--- before/src/ProcessingPanel.test.tsx
+++ after/src/ProcessingPanel.test.tsx
@@ -0,0 +1,53 @@
+import { act, cleanup, render, screen, within } from '@testing-library/react'
+import { afterEach, describe, expect, it, vi } from 'vitest'
+import { ProcessingPanel } from './ProcessingPanel'
+import type { ProcessingRun, ProcessingStage } from './types'
+
+const stage = (key: string, status: ProcessingStage['status'], values: Partial<ProcessingStage> = {}): ProcessingStage => ({
+  key, attempt: 1, status, started_at: null, finished_at: null, duration_ms: null, error_code: null, ...values,
+})
+const run = (stages: ProcessingStage[], values: Partial<ProcessingRun> = {}): ProcessingRun => ({
+  id: 'r-1', operation: 'transcribe', status: 'running', started_at: '2026-09-30T00:00:00Z', finished_at: null, stages, ...values,
+})
+afterEach(() => { cleanup(); vi.useRealTimers() })
+
+describe('processing status', () => {
+  it('pending_has_no_fake_duration', () => {
+    render(<ProcessingPanel runs={[run([stage('stt', 'pending')])]} />)
+    const item = screen.getByText('Распознавание речи').closest('li')!
+    expect(within(item).getByText('Ожидает')).toBeVisible()
+    expect(within(item).queryByText(/\d+[,.]\d+ с/)).not.toBeInTheDocument()
+  })
+
+  it('running_elapsed_updates_then_stops', () => {
+    vi.useFakeTimers()
+    vi.setSystemTime(new Date('2026-09-30T00:00:02Z'))
+    const initial = run([stage('stt', 'running', { started_at: '2026-09-30T00:00:00Z' })])
+    const view = render(<ProcessingPanel runs={[initial]} />)
+    expect(screen.getByText('2,0 с')).toBeVisible()
+    act(() => vi.advanceTimersByTime(2000))
+    expect(screen.getByText('4,0 с')).toBeVisible()
+    view.rerender(<ProcessingPanel runs={[run([stage('stt', 'done', { started_at: '2026-09-30T00:00:00Z', finished_at: '2026-09-30T00:00:03Z', duration_ms: 3000 })], { status: 'done', finished_at: '2026-09-30T00:00:03Z' })]} />)
+    expect(screen.getByText('3,0 с')).toBeVisible()
+    act(() => vi.advanceTimersByTime(5000))
+    expect(screen.getByText('3,0 с')).toBeVisible()
+    expect(screen.queryByText('9,0 с')).not.toBeInTheDocument()
+  })
+
+  it('failed_stage_keeps_completed_timings', () => {
+    render(<ProcessingPanel runs={[run([
+      stage('stt', 'done', { duration_ms: 4200 }),
+      stage('normalization', 'error', { error_code: 'NORMALIZATION_FAILED' }),
+      stage('pii_masking', 'pending'),
+    ], { status: 'error', finished_at: '2026-09-30T00:00:05Z' })]} />)
+    expect(within(screen.getByText('Распознавание речи').closest('li')!).getByText('4,2 с')).toBeVisible()
+    expect(within(screen.getByText('Нормализация текста').closest('li')!).getByText(/Ошибка нормализации/)).toBeVisible()
+    expect(within(screen.getByText('Маскирование персональных данных').closest('li')!).getByText('Ожидает')).toBeVisible()
+  })
+
+  it('legacy_empty_history_is_unknown', () => {
+    render(<ProcessingPanel runs={[]} />)
+    expect(screen.getByText(/История обработки недоступна/)).toBeVisible()
+    expect(screen.getByText(/Длительность неизвестна/)).toBeVisible()
+  })
+})

```

## src/PrivacyPanel.tsx
```diff
--- before/src/PrivacyPanel.tsx
+++ after/src/PrivacyPanel.tsx
@@ -0,0 +1,30 @@
+import type { Document, Transcript } from './types'
+
+export function PrivacyPanel({ transcript, document }: { transcript: Transcript; document: Document | null }) {
+  const counts = transcript.pii_entities.reduce<Record<string, number>>((result, entity) => {
+    result[entity.type] = (result[entity.type] ?? 0) + 1
+    return result
+  }, {})
+  const sentRevision = document?.source_transcript_revision ?? null
+  const currentWasUsed = sentRevision === transcript.revision
+
+  return <section aria-labelledby="privacy-heading" className="privacy-panel">
+    <h2 id="privacy-heading">Маскирование и передача данных</h2>
+    <p>Текущая транскрипция: Версия {transcript.revision}</p>
+    <p>Обнаружено: {transcript.pii_entities.length}</p>
+    {transcript.pii_entities.length > 0 && <ul aria-label="Обнаруженные типы данных">
+      {Object.entries(counts).sort(([a], [b]) => a.localeCompare(b)).map(([type, count]) => <li key={type}>{type}: {count}</li>)}
+    </ul>}
+    <p>Маскирование выполняется по правилам и может пропустить персональные данные. Нулевое число обнаружений не гарантирует их отсутствия.</p>
+    <h3>Текущий обезличенный текст</h3>
+    <p className="whitespace-pre-wrap">{transcript.masked_text || 'Текст отсутствует'}</p>
+    {!currentWasUsed && <p>Будет отправлено при генерации: Версия {transcript.revision}</p>}
+    {document && <div>
+      {sentRevision === null ? <p>Источник прошлой генерации неизвестен.</p> :
+        <p>Источник последней генерации: Версия {sentRevision}</p>}
+      {document.source_masked_text === null ? <p>Отправленный при прошлой генерации текст неизвестен.</p> :
+        <p className="whitespace-pre-wrap">{document.source_masked_text}</p>}
+    </div>}
+    <p>Аудиозапись остаётся локальной. Перед генерацией исправленный текст маскируется заново.</p>
+  </section>
+}

```

## src/PrivacyPanel.test.tsx
```diff
--- before/src/PrivacyPanel.test.tsx
+++ after/src/PrivacyPanel.test.tsx
@@ -0,0 +1,46 @@
+import { cleanup, render, screen } from '@testing-library/react'
+import { afterEach, describe, expect, it } from 'vitest'
+import { PrivacyPanel } from './PrivacyPanel'
+import { emptyClinicalData } from './clinical'
+import type { Document, Transcript } from './types'
+
+const transcript: Transcript = {
+  raw_text: 'Исходный текст', normalized_text: 'Текущий текст', masked_text: 'Пациент [PERSON_1]', current_text: 'Текущий текст',
+  language: 'ru', duration_seconds: 2, stt_model: 'demo', revision: 2, audio_available: false,
+  segments: [{ id: 'seg-000001', start: 0, end: 2, text: 'Текущий текст', speaker: null }],
+  pii_entities: [{ type: 'PERSON', placeholder: '[PERSON_1]' }, { type: 'PERSON', placeholder: '[PERSON_2]' }, { type: 'PHONE', placeholder: '[PHONE_1]' }],
+}
+const document: Document = {
+  id: 'd-1', consultation_id: 'c-1', ai_generated_data: emptyClinicalData, doctor_approved_data: null, data: emptyClinicalData,
+  llm_provider: 'demo', llm_model: 'demo', updated_at: '2026-09-30T00:00:00Z', version: 1,
+  source_transcript_revision: 1, source_masked_text: 'Старая обезличенная версия', evidence: [],
+}
+afterEach(cleanup)
+
+describe('privacy disclosure', () => {
+  it('counts detected entities from the current transcript', () => {
+    render(<PrivacyPanel transcript={transcript} document={document} />)
+    expect(screen.getByText('PERSON: 2')).toBeVisible()
+    expect(screen.getByText('PHONE: 1')).toBeVisible()
+    expect(screen.getByText('Пациент [PERSON_1]')).toBeVisible()
+  })
+
+  it('zero is not a privacy guarantee', () => {
+    render(<PrivacyPanel transcript={{ ...transcript, pii_entities: [] }} document={null} />)
+    expect(screen.getByText(/Обнаружено: 0/)).toBeVisible()
+    expect(screen.getByText(/Маскирование выполняется по правилам и может пропустить персональные данные/)).toBeVisible()
+  })
+
+  it('marks revision two as pending when the last generation used revision one', () => {
+    render(<PrivacyPanel transcript={transcript} document={document} />)
+    expect(screen.getByText('Будет отправлено при генерации: Версия 2')).toBeVisible()
+    expect(screen.getByText('Источник последней генерации: Версия 1')).toBeVisible()
+    expect(screen.getByText('Старая обезличенная версия')).toBeVisible()
+  })
+
+  it('never reconstructs unknown legacy generation input from current text', () => {
+    render(<PrivacyPanel transcript={transcript} document={{ ...document, source_transcript_revision: null, source_masked_text: null }} />)
+    expect(screen.getByText(/Источник прошлой генерации неизвестен/)).toBeVisible()
+    expect(screen.getByText(/Будет отправлено при генерации/)).toBeVisible()
+  })
+})

```

## src/api.test.ts
```diff
--- before/src/api.test.ts
+++ after/src/api.test.ts
@@ -0,0 +1,77 @@
+import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
+import { api, ApiError, hasToken, setToken } from './api'
+
+beforeEach(() => setToken('test-token'))
+afterEach(() => { setToken(null); vi.unstubAllGlobals(); vi.restoreAllMocks() })
+
+describe('authenticated file requests', () => {
+  it.each(['audio', 'pdf'] as const)('%s sends a bearer header without putting the token in the URL or storing clinical bytes', async method => {
+    const storage = vi.spyOn(Storage.prototype, 'setItem')
+    const bytes = new Uint8Array([37, 80, 68, 70])
+    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
+      const request = new Request(new URL(String(input), 'http://localhost'), init)
+      expect(request.headers.get('Authorization')).toBe('Bearer test-token')
+      expect(request.url).not.toContain('test-token')
+      expect(request.url).toContain(`/consultations/c-1/${method === 'pdf' ? 'document.pdf' : 'audio'}`)
+      return new Response(bytes)
+    })
+    vi.stubGlobal('fetch', fetcher)
+    const blob = await api[method]('c-1')
+    expect(Array.from(new Uint8Array(await blob.arrayBuffer()))).toEqual(Array.from(bytes))
+    expect(fetcher).toHaveBeenCalledOnce()
+    expect(storage).not.toHaveBeenCalled()
+  })
+
+  it.each(['audio', 'pdf', 'downloadDocx'] as const)('%s shares 401 logout behavior', async method => {
+    const unauthorized = vi.fn()
+    window.addEventListener('medhub-unauthorized', unauthorized, { once: true })
+    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'Войдите снова' }), { status: 401, headers: { 'Content-Type': 'application/json' } })))
+    await expect(api[method]('c-1')).rejects.toMatchObject({ status: 401, message: 'Войдите снова' })
+    expect(hasToken()).toBe(false)
+    expect(sessionStorage.getItem('medhub.session.token')).toBeNull()
+    expect(unauthorized).toHaveBeenCalledOnce()
+  })
+
+  it('preserves cancellation instead of reporting a connection error', async () => {
+    const controller = new AbortController()
+    vi.stubGlobal('fetch', vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
+      init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
+    })))
+    const pending = api.pdf('c-1', controller.signal)
+    controller.abort()
+    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
+    expect(hasToken()).toBe(true)
+  })
+
+  it('reports AbortError when a canceled fetch rejects with a generic network error', async () => {
+    const controller = new AbortController()
+    controller.abort()
+    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
+    await expect(api.audio('c-1', controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
+  })
+
+  it('sends a revision-scoped transcript edit as JSON', async () => {
+    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
+      const request = new Request(new URL(String(input), 'http://localhost'), init)
+      expect(request.method).toBe('PATCH')
+      expect(request.url).toContain('/consultations/c-1/transcript')
+      expect(request.headers.get('Content-Type')).toBe('application/json')
+      expect(await request.json()).toEqual({ expected_revision: 2, changes: [{ segment_id: 'seg-000001', text: 'Исправлено' }] })
+      return new Response(JSON.stringify({ revision: 3 }), { headers: { 'Content-Type': 'application/json' } })
+    }))
+    await expect(api.editTranscript('c-1', 2, [{ segment_id: 'seg-000001', text: 'Исправлено' }])).resolves.toMatchObject({ revision: 3 })
+  })
+
+  it('uses a safe error when a file response is not JSON', async () => {
+    vi.stubGlobal('fetch', vi.fn(async () => new Response('proxy failure', { status: 502 })))
+    await expect(api.pdf('c-1')).rejects.toBeInstanceOf(ApiError)
+    await expect(api.pdf('c-1')).rejects.toMatchObject({ status: 502 })
+  })
+
+  it('retains the DOCX-specific connection message', async () => {
+    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
+    await expect(api.downloadDocx('c-1')).rejects.toMatchObject({
+      status: 0, message: 'Не удалось скачать документ. Проверьте соединение.',
+    })
+  })
+})

```

## src/DocumentEditor.test.tsx
```diff
--- before/src/DocumentEditor.test.tsx
+++ after/src/DocumentEditor.test.tsx
@@ -4,17 +4,17 @@
 import { DocumentEditor } from './DocumentEditor'
 import { emptyClinicalData } from './clinical'
 import type { ClinicalData, ConsultationTemplate, Document } from './types'
 
 const template: ConsultationTemplate = { id: 'cardiologist', name: 'Осмотр кардиолога', fields: [
   { key: 'rhythm', label: 'Ритм сердца', prompt: 'Ритм сердца, частота и особенности', section: 'Осмотр' },
   { key: 'diagnosis', label: 'Диагноз', prompt: 'Диагноз', section: 'Заключение', clinical_field: 'diagnosis' },
 ] }
-const document: Document = { id: 'doc-1', consultation_id: 'c-1', ai_generated_data: emptyClinicalData, doctor_approved_data: null, data: emptyClinicalData, llm_provider: 'demo', llm_model: 'demo', updated_at: '2026-09-30T00:00:00Z', version: 1 }
+const document: Document = { id: 'doc-1', consultation_id: 'c-1', ai_generated_data: emptyClinicalData, doctor_approved_data: null, data: emptyClinicalData, llm_provider: 'demo', llm_model: 'demo', updated_at: '2026-09-30T00:00:00Z', version: 1, source_transcript_revision: 1, source_masked_text: null, evidence: [] }
 afterEach(() => { cleanup(); vi.unstubAllGlobals() })
 
 describe('doctor document editor', () => {
   it('saves specialty fields with medication and vitals, then enables approval of saved version', async () => {
     let saved: ClinicalData | null = null
     const onSave = vi.fn(async (data: ClinicalData, version: number) => { expect(version).toBe(1); saved = data; return { ...document, data, version: 2 } })
     const onApprove = vi.fn(async (_version: number) => undefined)
     const props = { document, template, status: 'AI_GENERATED' as const, busy: false, regenerationRevision: 0, onSave, onApprove, onReload: vi.fn(async () => document), onDirtyChange: vi.fn() }

```

