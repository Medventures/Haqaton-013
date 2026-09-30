# Task7 frozen implementation review

Read task-7-brief.md/context/task-7-report.md/task-reviewer-prompt.md. Implementer p0_panels; reviewer must be distinct. Scope original approved P0 ONLY; new requested sparse/QR/protocol features pendingdesign and not missingrequirements here. Task8 separately reviewed component, here examine approved-only wiring/unmount. Task6 whiteness class minor included. Base snapshot taken afterTask6. No Git. Report57tests/buildgreen; actualbrowser375px/keyboard Task9 pending.

## src/TranscriptPanel.tsx
```diff
--- /dev/null	2026-09-30 09:14:26.461931627 +0500
+++ src/TranscriptPanel.tsx	2026-09-30 14:40:01.438203429 +0500
@@ -0,0 +1,104 @@
+import { useEffect, useRef, useState } from 'react'
+import { AudioLines, Clock3, Save } from 'lucide-react'
+import { ApiError, api } from './api'
+import { Button } from './ui'
+import { formatTime } from './utils'
+import type { Transcript, TranscriptTextChange } from './types'
+import type { SourceSelection } from './SourceEvidence'
+
+type Props = { consultationId: string; transcript: Transcript; editable: boolean; selection: SourceSelection | null; onSave: (changes: TranscriptTextChange[], expectedRevision: number) => Promise<void>; onDirtyChange: (dirty: boolean) => void; onReload?: () => Promise<Transcript> }
+
+function segmentDraft(transcript: Transcript): Record<string, string> {
+  return Object.fromEntries(transcript.segments.map(segment => [segment.id, segment.text]))
+}
+
+export function TranscriptPanel({ consultationId, transcript, editable, selection, onSave, onDirtyChange, onReload }: Props) {
+  const [view, setView] = useState<'segments' | 'normalized' | 'masked'>('segments')
+  const [editing, setEditing] = useState(false)
+  const [draft, setDraft] = useState(() => segmentDraft(transcript))
+  const [saving, setSaving] = useState(false)
+  const [error, setError] = useState('')
+  const [conflict, setConflict] = useState(false)
+  const [audioUrl, setAudioUrl] = useState<string | null>(null)
+  const [audioError, setAudioError] = useState(false)
+  const audioRef = useRef<HTMLAudioElement>(null)
+  const [loadedTranscript, setLoadedTranscript] = useState(transcript)
+  const dirty = transcript.segments.some(segment => (draft[segment.id] ?? segment.text) !== segment.text)
+
+  useEffect(() => {
+    setDraft(segmentDraft(transcript))
+    setLoadedTranscript(transcript)
+    setEditing(false)
+    setError('')
+    setConflict(false)
+  }, [consultationId, transcript.revision])
+  useEffect(() => { onDirtyChange(editing && dirty) }, [editing, dirty, onDirtyChange])
+  useEffect(() => {
+    if (!selection || !transcript.audio_available) return
+    let active = true
+    let url: string | null = null
+    const controller = new AbortController()
+    setAudioError(false)
+    void api.audio(consultationId, controller.signal).then(blob => {
+      if (!active) return
+      url = URL.createObjectURL(blob)
+      setAudioUrl(url)
+    }).catch(cause => {
+      if (active && !(cause instanceof Error && cause.name === 'AbortError')) setAudioError(true)
+    })
+    return () => {
+      active = false
+      controller.abort()
+      if (url) URL.revokeObjectURL(url)
+      setAudioUrl(null)
+    }
+  }, [consultationId, Boolean(selection), transcript.audio_available])
+  useEffect(() => {
+    if (selection && audioRef.current && audioRef.current.readyState >= 1) audioRef.current.currentTime = selection.start
+  }, [selection, audioUrl])
+
+  const changes = transcript.segments.filter(segment => (draft[segment.id] ?? segment.text) !== segment.text)
+    .map(segment => ({ segment_id: segment.id, text: draft[segment.id] }))
+
+  async function save() {
+    if (!changes.length) return
+    setSaving(true)
+    setError('')
+    setConflict(false)
+    try {
+      await onSave(changes, transcript.revision)
+      setEditing(false)
+      onDirtyChange(false)
+    } catch (cause) {
+      setConflict(cause instanceof ApiError && cause.status === 409)
+      setError(cause instanceof Error ? cause.message : 'Не удалось сохранить исправления')
+    } finally { setSaving(false) }
+  }
+
+  async function reload() {
+    if (dirty && !window.confirm('Загрузить актуальную транскрипцию? Ваши несохранённые исправления будут потеряны.')) return
+    if (!onReload) { window.location.reload(); return }
+    try {
+      const current = await onReload()
+      setLoadedTranscript(current)
+      setDraft(segmentDraft(current))
+      setEditing(false)
+      setConflict(false)
+      setError('')
+      onDirtyChange(false)
+    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось загрузить транскрипцию') }
+  }
+
+  const visible = loadedTranscript.revision === transcript.revision ? transcript : loadedTranscript
+  return <div className="transcript-panel">
+    <div className="panel-heading"><div className="heading-icon"><AudioLines size={20} /></div><div><p className="eyebrow">РАЗГОВОР</p><h2>Транскрипция</h2></div><span className="version-chip">Версия {visible.revision}</span></div>
+    <div className="transcript-meta"><span><Clock3 size={14} /> {formatTime(visible.duration_seconds)}</span><span>{visible.language?.toUpperCase() || 'RU'}</span><span>{visible.stt_model}</span></div>
+    <div className="view-tabs" role="tablist" aria-label="Вид транскрипции"><button role="tab" aria-selected={view === 'segments'} onClick={() => setView('segments')}>Разговор</button><button role="tab" aria-selected={view === 'normalized'} onClick={() => setView('normalized')}>Текст</button><button role="tab" aria-selected={view === 'masked'} onClick={() => setView('masked')}>Обезличено</button></div>
+    {selection && <div className="selected-source" role="status"><span>Фрагмент записи · {formatTime(selection.start)}</span><q>{selection.quote}</q>{(!visible.audio_available || audioError) && <span>Аудиозапись недоступна</span>}</div>}
+    {audioUrl && selection && visible.audio_available && <audio ref={audioRef} src={audioUrl} controls aria-label="Аудиозапись консультации" onLoadedMetadata={event => { event.currentTarget.currentTime = selection.start }} />}
+    <div className="transcript-scroll">{view === 'segments' ? (visible.segments.length ? visible.segments.map((segment, index) => <div className={`segment ${selection?.segmentId === segment.id ? 'selected' : ''}`} key={segment.id}><span className="segment-time">{formatTime(segment.start)}</span><div><span className="segment-speaker">{segment.speaker || 'Участник разговора'}</span>{editing ? <textarea aria-label={`Фрагмент ${index + 1}`} value={draft[segment.id] ?? segment.text} maxLength={20000} rows={3} className="input resize-y" onChange={event => setDraft(current => ({ ...current, [segment.id]: event.target.value }))} /> : <p>{segment.text}</p>}</div></div>) : <p className="transcript-prose">{visible.current_text || 'Текст не распознан.'}</p>) : <p className="transcript-prose whitespace-pre-wrap">{view === 'normalized' ? visible.normalized_text : visible.masked_text}</p>}</div>
+    {view === 'masked' && <div className="privacy-footer">Маскирование выполняется по правилам и может пропустить персональные данные.</div>}
+    {editable && <div className="transcript-actions">{editing ? <><Button type="button" onClick={() => void save()} disabled={!changes.length || saving || !Object.values(draft).some(value => value.trim())}><Save size={16} /> {saving ? 'Сохраняем…' : 'Сохранить исправления'}</Button><Button type="button" variant="secondary" onClick={() => { setDraft(segmentDraft(visible)); setEditing(false); setError(''); setConflict(false) }} disabled={saving}>Отмена</Button></> : <Button type="button" variant="secondary" onClick={() => { setEditing(true); setView('segments') }}>Исправить текст</Button>}</div>}
+    {error && <p role="alert" className="action-error">{error}{conflict && <> Версия транскрипции изменилась. Ваши исправления сохранены в форме. <button type="button" onClick={() => void reload()}>Загрузить актуальную версию</button></>}</p>}
+  </div>
+}

```

## src/TranscriptPanel.test.tsx
```diff
--- /dev/null	2026-09-30 09:14:26.461931627 +0500
+++ src/TranscriptPanel.test.tsx	2026-09-30 14:49:52.357027331 +0500
@@ -0,0 +1,69 @@
+import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
+import { afterEach, describe, expect, it, vi } from 'vitest'
+import { ApiError, api } from './api'
+import { TranscriptPanel } from './TranscriptPanel'
+import type { Transcript } from './types'
+
+const transcript: Transcript = { raw_text: 'Исходная речь', current_text: 'Исходная речь', normalized_text: 'Исходная речь', masked_text: 'Исходная речь', language: 'ru', duration_seconds: 5, stt_model: 'demo', revision: 1, audio_available: true, segments: [{ id: 'seg-000001', start: 1.25, end: 3, text: 'Исходная речь', speaker: null }], pii_entities: [] }
+const props = { consultationId: 'c-1', transcript, editable: true, selection: null, onSave: vi.fn(async () => {}), onDirtyChange: vi.fn() }
+const NativeURL = URL
+afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
+
+describe('transcript correction and playback', () => {
+  it('sends text-only changes with the expected revision', async () => {
+    const onSave = vi.fn(async () => {})
+    render(<TranscriptPanel {...props} onSave={onSave} />)
+    fireEvent.click(screen.getByRole('button', { name: /Исправить текст/ }))
+    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Исправленная речь' } })
+    fireEvent.click(screen.getByRole('button', { name: /Сохранить исправления/ }))
+    await waitFor(() => expect(onSave).toHaveBeenCalledWith([{ segment_id: 'seg-000001', text: 'Исправленная речь' }], 1))
+  })
+
+  it('retains unsaved text and offers conflict resolution after 409', async () => {
+    render(<TranscriptPanel {...props} onSave={vi.fn(async () => { throw new ApiError('Версия устарела', 409) })} />)
+    fireEvent.click(screen.getByRole('button', { name: /Исправить текст/ }))
+    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Моя правка' } })
+    fireEvent.click(screen.getByRole('button', { name: /Сохранить исправления/ }))
+    await screen.findByText(/Версия транскрипции изменилась/)
+    expect(screen.getByRole('textbox', { name: /Фрагмент 1/ })).toHaveValue('Моя правка')
+    expect(screen.getByRole('button', { name: /Загрузить актуальную версию/ })).toBeVisible()
+  })
+
+  it.each(['APPROVED', 'SENT_TO_MIS'])('keeps %s transcript read-only', () => {
+    render(<TranscriptPanel {...props} editable={false} />)
+    expect(screen.queryByRole('button', { name: /Исправить текст/ })).not.toBeInTheDocument()
+  })
+
+  it('uses server time for selected audio and revokes its URL on consultation switch', async () => {
+    vi.spyOn(api, 'audio').mockResolvedValue(new Blob(['synthetic']))
+    const create = vi.fn(() => 'blob:synthetic-1')
+    const revoke = vi.fn()
+    vi.stubGlobal('URL', class extends NativeURL { static createObjectURL = create; static revokeObjectURL = revoke })
+    const selection = { segmentId: 'seg-000001', start: 1.25, quote: 'Исходная речь' }
+    const view = render(<TranscriptPanel {...props} selection={selection} />)
+    const audio = await screen.findByLabelText('Аудиозапись консультации') as HTMLAudioElement
+    fireEvent.loadedMetadata(audio)
+    expect(audio.currentTime).toBe(1.25)
+    expect(view.container.querySelector('.segment')).toHaveClass('selected')
+    view.rerender(<TranscriptPanel {...props} consultationId="c-2" selection={null} />)
+    await waitFor(() => expect(revoke).toHaveBeenCalledWith('blob:synthetic-1'))
+  })
+
+  it('keeps source quote and time visible without audio', () => {
+    render(<TranscriptPanel {...props} transcript={{ ...transcript, audio_available: false }} selection={{ segmentId: 'seg-000001', start: 1.25, quote: 'Кашель три дня' }} />)
+    expect(screen.getByText('Кашель три дня')).toBeVisible()
+    expect(screen.getByText(/Аудиозапись недоступна/)).toBeVisible()
+    expect(screen.getAllByText(/00:01/)[0]).toBeVisible()
+  })
+
+  it('discards a late audio fetch after consultation switch', async () => {
+    let resolve!: (blob: Blob) => void
+    vi.spyOn(api, 'audio').mockImplementation(() => new Promise<Blob>(done => { resolve = done }))
+    const create = vi.fn(() => 'blob:late')
+    vi.stubGlobal('URL', class extends NativeURL { static createObjectURL = create; static revokeObjectURL = vi.fn() })
+    const view = render(<TranscriptPanel {...props} selection={{ segmentId: 'seg-000001', start: 1.25, quote: 'Речь' }} />)
+    view.rerender(<TranscriptPanel {...props} consultationId="c-2" selection={null} />)
+    await act(async () => resolve(new Blob(['late'])))
+    expect(create).not.toHaveBeenCalled()
+  })
+})

```

## src/SourceEvidence.tsx
```diff
--- /dev/null	2026-09-30 09:14:26.461931627 +0500
+++ src/SourceEvidence.tsx	2026-09-30 14:48:01.828550667 +0500
@@ -0,0 +1,44 @@
+import type { ClinicalData, EvidenceLink } from './types'
+
+export type SourceSelection = { segmentId: string; start: number; quote: string }
+
+type Props = { fieldPath: string; aiData: ClinicalData; currentData: ClinicalData; evidence: EvidenceLink[]; onSelect: (selection: SourceSelection) => void }
+
+function valueAt(data: ClinicalData, path: string): unknown {
+  const [root, part, leaf] = path.split('/')
+  if (root === 'template_fields') return data.template_fields.find(field => field.key === part)?.value
+  const value = data[root as keyof ClinicalData]
+  if (part === undefined) return value
+  if (!Array.isArray(value)) return value && typeof value === 'object' ? (value as unknown as Record<string, unknown>)[part] : undefined
+  const item = value[Number(part)]
+  return leaf && item && typeof item === 'object' ? (item as unknown as Record<string, unknown>)[leaf] : item
+}
+
+function arrayChanged(aiData: ClinicalData, currentData: ClinicalData, path: string): boolean {
+  const root = path.split('/')[0] as keyof ClinicalData
+  if (root === 'template_fields') return false
+  const original = aiData[root]
+  const current = currentData[root]
+  return Array.isArray(original) && JSON.stringify(original) !== JSON.stringify(current)
+}
+
+function showValue(value: unknown): string {
+  if (value == null || value === '') return 'Не указано'
+  if (typeof value === 'string') return value
+  return JSON.stringify(value)
+}
+
+export function SourceEvidence({ fieldPath, aiData, currentData, evidence, onSelect }: Props) {
+  const aiValue = valueAt(aiData, fieldPath)
+  const changed = arrayChanged(aiData, currentData, fieldPath) || JSON.stringify(aiValue) !== JSON.stringify(valueAt(currentData, fieldPath))
+  const links = evidence.filter(link => link.field_path === fieldPath)
+
+  return <div className="source-evidence" data-field-path={fieldPath}>
+    <p>{changed ? 'Источник AI-версии · Поле изменено врачом' : 'Источник текущего поля · AI-версия'}</p>
+    {changed && <p>Исходное значение AI: {showValue(aiValue)}</p>}
+    {links.length === 0 ? <p>Источник не записан для этой генерации.</p> : links.map((link, index) =>
+      <button type="button" className="source-quote" key={`${link.segment_id}-${index}`} onClick={() => onSelect({ segmentId: link.segment_id, start: link.start, quote: link.quote })} aria-label={`Показать фрагмент записи: ${link.quote}`}>
+        <span>Фрагмент записи</span><q>{link.quote}</q>
+      </button>)}
+  </div>
+}

```

## src/SourceEvidence.test.tsx
```diff
--- /dev/null	2026-09-30 09:14:26.461931627 +0500
+++ src/SourceEvidence.test.tsx	2026-09-30 14:49:52.314026756 +0500
@@ -0,0 +1,43 @@
+import { cleanup, fireEvent, render, screen } from '@testing-library/react'
+import { afterEach, describe, expect, it, vi } from 'vitest'
+import { emptyClinicalData } from './clinical'
+import { SourceEvidence } from './SourceEvidence'
+import type { ClinicalData, EvidenceLink } from './types'
+
+const source = (path: string): EvidenceLink => ({ field_path: path, segment_id: 'seg-000001', quote: 'Кашель три дня', transcript_revision: 1, start: 12, end: 14 })
+const ai: ClinicalData = { ...emptyClinicalData, complaints: ['Кашель', 'Одышка'], medications: [{ name: 'Препарат А', dosage: '10 мг', frequency: null, duration: null }, { name: 'Препарат Б', dosage: '20 мг', frequency: null, duration: null }], diagnosis: 'Острый бронхит', template_fields: [{ key: 'rhythm', value: 'Ритмичный' }, { key: 'tone', value: 'Ясный' }] }
+afterEach(cleanup)
+
+describe('AI source links', () => {
+  it('shows original value and quote when a scalar changes', () => {
+    const onSelect = vi.fn()
+    render(<SourceEvidence fieldPath="diagnosis" aiData={ai} currentData={{ ...ai, diagnosis: 'Другой диагноз' }} evidence={[source('diagnosis')]} onSelect={onSelect} />)
+    expect(screen.getByText(/Источник AI-версии/)).toBeVisible()
+    expect(screen.getByText(/Исходное значение AI: Острый бронхит/)).toBeVisible()
+    fireEvent.click(screen.getByRole('button', { name: /Кашель три дня/ }))
+    expect(onSelect).toHaveBeenCalledWith({ segmentId: 'seg-000001', start: 12, quote: 'Кашель три дня' })
+  })
+
+  it.each([
+    ['medications/0/name', { ...ai, medications: [ai.medications[1], ai.medications[0]] }],
+    ['medications/0/dosage', { ...ai, medications: [ai.medications[1]] }],
+    ['medications/0/name', { ...ai, medications: [ai.medications[0], ai.medications[0]] }],
+    ['complaints/0', { ...ai, complaints: ['Новый пункт', ...ai.complaints] }],
+    ['complaints/0', { ...ai, complaints: ['Кашель', 'Кашель'] }],
+  ] as [string, ClinicalData][])('detaches %s when its containing array changes', (fieldPath, currentData) => {
+    render(<SourceEvidence fieldPath={fieldPath} aiData={ai} currentData={currentData} evidence={[source(fieldPath)]} onSelect={vi.fn()} />)
+    expect(screen.getByText(/Источник AI-версии/)).toBeVisible()
+    expect(screen.queryByText(/Источник текущего поля/)).not.toBeInTheDocument()
+  })
+
+  it('keeps specialty citations with their stable key after display reorder', () => {
+    render(<SourceEvidence fieldPath="template_fields/rhythm" aiData={ai} currentData={{ ...ai, template_fields: [...ai.template_fields].reverse() }} evidence={[source('template_fields/rhythm')]} onSelect={vi.fn()} />)
+    expect(screen.getByText(/Источник текущего поля/)).toBeVisible()
+    expect(screen.queryByText(/Поле изменено/)).not.toBeInTheDocument()
+  })
+
+  it('labels absent evidence as unavailable', () => {
+    render(<SourceEvidence fieldPath="diagnosis" aiData={ai} currentData={ai} evidence={[]} onSelect={vi.fn()} />)
+    expect(screen.getByText(/Источник не записан/)).toBeVisible()
+  })
+})

```

## src/Workspace.test.tsx
```diff
--- /dev/null	2026-09-30 09:14:26.461931627 +0500
+++ src/Workspace.test.tsx	2026-09-30 14:49:52.405027973 +0500
@@ -0,0 +1,109 @@
+import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
+import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
+import App from './App'
+import { ApiError, api, setToken } from './api'
+import { emptyClinicalData } from './clinical'
+import type { Consultation, ConsultationTemplate, Document, Transcript } from './types'
+
+const template: ConsultationTemplate = { id: 'therapist', name: 'Осмотр терапевта', fields: [] }
+const transcript: Transcript = { raw_text: 'Исходная речь', normalized_text: 'Исходная речь', masked_text: 'Исходная речь', current_text: 'Исходная речь', language: 'ru', duration_seconds: 3, stt_model: 'demo', revision: 1, audio_available: false, segments: [{ id: 'seg-000001', start: 0, end: 3, text: 'Исходная речь', speaker: null }], pii_entities: [] }
+const document: Document = { id: 'd-1', consultation_id: 'c-1', ai_generated_data: emptyClinicalData, doctor_approved_data: null, data: emptyClinicalData, llm_provider: 'demo', llm_model: 'demo', updated_at: '2026-09-30T00:00:00Z', version: 1, source_transcript_revision: 1, source_masked_text: 'Исходная речь', evidence: [] }
+function item(id: string, status: Consultation['status']): Consultation { return { id, external_patient_id: id === 'c-1' ? 'SYN-1' : 'SYN-2', template_id: 'therapist', status, created_at: '2026-09-30T00:00:00Z', updated_at: '2026-09-30T00:00:00Z', approved_at: status === 'APPROVED' ? '2026-09-30T00:00:00Z' : null, error_message: null, transcript_revision: status === 'RECORDING' ? null : 1, audio_available: status === 'RECORDING', processing_runs: [] } }
+
+function setup(status: Consultation['status'] = 'AI_GENERATED') {
+  let current = item('c-1', status)
+  vi.spyOn(api, 'health').mockResolvedValue({ status: 'ok', mode: 'demo', stt_model: 'demo', llm_provider: 'demo', llm_model: 'demo', mis_provider: 'mock' })
+  vi.spyOn(api, 'me').mockResolvedValue({ id: 'u-1', username: 'doctor', role: 'doctor', display_name: 'Врач' })
+  vi.spyOn(api, 'consultations').mockImplementation(async () => [current, item('c-2', 'CREATED')])
+  vi.spyOn(api, 'consultation').mockImplementation(async id => id === 'c-1' ? current : item('c-2', 'CREATED'))
+  vi.spyOn(api, 'templates').mockResolvedValue([template])
+  vi.spyOn(api, 'transcript').mockResolvedValue(transcript)
+  vi.spyOn(api, 'document').mockResolvedValue(document)
+  vi.spyOn(api, 'audit').mockResolvedValue([])
+  return { update: (next: Consultation) => { current = next } }
+}
+
+beforeEach(() => { setToken('test-token'); window.history.replaceState(null, '', '/') })
+afterEach(() => { window.dispatchEvent(new Event('medhub-unauthorized')); cleanup(); setToken(null); vi.restoreAllMocks(); vi.unstubAllGlobals() })
+
+describe('workspace trust workflow', () => {
+  it('transcript_save_confirms_draft_invalidation_and_clears_cached_editor even after an old fetch returns', async () => {
+    const state = setup()
+    let resolveDocument!: (value: Document) => void
+    vi.mocked(api.document).mockImplementation(() => new Promise<Document>(resolve => { resolveDocument = resolve }))
+    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
+    vi.spyOn(api, 'editTranscript').mockImplementation(async () => {
+      state.update({ ...item('c-1', 'TRANSCRIBED'), transcript_revision: 2 })
+      return { ...transcript, revision: 2, current_text: 'Исправлено', segments: [{ ...transcript.segments[0], text: 'Исправлено' }] }
+    })
+    render(<App />)
+    fireEvent.click(await screen.findByRole('button', { name: /Исправить текст/ }))
+    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Исправлено' } })
+    fireEvent.click(screen.getByRole('button', { name: /Сохранить исправления/ }))
+    await waitFor(() => expect(api.editTranscript).toHaveBeenCalledWith('c-1', 1, [{ segment_id: 'seg-000001', text: 'Исправлено' }]))
+    expect(confirm).toHaveBeenCalled()
+    expect(screen.queryByRole('form', { name: /документ/i })).not.toBeInTheDocument()
+    resolveDocument(document)
+    await waitFor(() => expect(screen.getByText('Версия 2')).toBeVisible())
+    expect(screen.queryByRole('form', { name: /документ/i })).not.toBeInTheDocument()
+  })
+
+  it('keeps transcript edits after a stale 409 and leaves the document visible', async () => {
+    setup()
+    vi.spyOn(window, 'confirm').mockReturnValue(true)
+    vi.spyOn(api, 'editTranscript').mockRejectedValue(new ApiError('Версия устарела', 409))
+    render(<App />)
+    await screen.findByRole('form', { name: /документ/i })
+    fireEvent.click(screen.getByRole('button', { name: /Исправить текст/ }))
+    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Моя правка' } })
+    fireEvent.click(screen.getByRole('button', { name: /Сохранить исправления/ }))
+    await screen.findByText(/Версия транскрипции изменилась/)
+    expect(screen.getByRole('textbox', { name: /Фрагмент 1/ })).toHaveValue('Моя правка')
+    expect(screen.getByRole('form', { name: /документ/i })).toBeVisible()
+  })
+
+  it('preserves the transcript draft when invalidation confirmation is declined', async () => {
+    setup()
+    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
+    const edit = vi.spyOn(api, 'editTranscript')
+    render(<App />)
+    await screen.findByRole('form', { name: /документ/i })
+    fireEvent.click(screen.getByRole('button', { name: /Исправить текст/ }))
+    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Моя правка' } })
+    fireEvent.click(screen.getByRole('button', { name: /Сохранить исправления/ }))
+    await waitFor(() => expect(confirm).toHaveBeenCalledOnce())
+    expect(edit).not.toHaveBeenCalled()
+    expect(screen.getByRole('textbox', { name: /Фрагмент 1/ })).toHaveValue('Моя правка')
+    expect(screen.getByRole('form', { name: /документ/i })).toBeVisible()
+  })
+
+  it('guards navigation and logout while transcript text is dirty', async () => {
+    setup()
+    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
+    render(<App />)
+    fireEvent.click(await screen.findByRole('button', { name: /Исправить текст/ }))
+    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Несохранённая правка' } })
+    fireEvent.click(screen.getByRole('button', { name: /SYN-2/ }))
+    expect(screen.getByRole('textbox', { name: /Фрагмент 1/ })).toHaveValue('Несохранённая правка')
+    fireEvent.click(screen.getByRole('button', { name: 'Выйти' }))
+    expect(confirm).toHaveBeenCalledTimes(2)
+    expect(screen.queryByText('Вход в MedHub')).not.toBeInTheDocument()
+  })
+
+  it('polls while a transcription promise is pending before PROCESSING appears', async () => {
+    setup('RECORDING')
+    vi.spyOn(api, 'transcribe').mockImplementation(() => new Promise<Transcript>(() => {}))
+    render(<App />)
+    fireEvent.click(await screen.findByRole('button', { name: /Транскрибировать аудио/ }))
+    await waitFor(() => expect(api.consultation).toHaveBeenCalledTimes(2), { timeout: 3500 })
+  })
+
+  it('offers authenticated PDF preview only for an approved document', async () => {
+    setup('APPROVED')
+    vi.spyOn(api, 'pdf').mockRejectedValue(new ApiError('Не удалось загрузить PDF', 502))
+    render(<App />)
+    const open = await screen.findByRole('button', { name: /Просмотреть PDF/ })
+    fireEvent.click(open)
+    expect(await screen.findByRole('dialog', { name: /Просмотр PDF/ })).toBeVisible()
+  })
+})

```

## src/App.tsx
```diff
--- /tmp/medhub-p0-snapshots.BPZlzl/task-7-base/src/App.tsx	2026-09-30 14:31:08.592657012 +0500
+++ src/App.tsx	2026-09-30 14:51:09.888065447 +0500
@@ -1,25 +1,32 @@
 import { useCallback, useEffect, useMemo, useState } from 'react'
 import * as Dialog from '@radix-ui/react-dialog'
 import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query'
-import { Activity, ArrowRight, AudioLines, Check, ChevronRight, CircleAlert, ClipboardCheck, Clock3, Download, FileClock, FileText, FlaskConical, History, LogOut, Menu, Plus, Search, ShieldCheck, Sparkles, Stethoscope, UploadCloud, X } from 'lucide-react'
+import { Activity, ArrowRight, AudioLines, Check, ChevronRight, CircleAlert, ClipboardCheck, Download, FileClock, FileText, FlaskConical, History, LogOut, Menu, Plus, Search, ShieldCheck, Sparkles, Stethoscope, UploadCloud, X } from 'lucide-react'
 import { api, ApiError, hasToken, setToken } from './api'
 import { DocumentEditor } from './DocumentEditor'
+import { PdfPreview } from './PdfPreview'
+import { PrivacyPanel } from './PrivacyPanel'
+import { ProcessingPanel } from './ProcessingPanel'
 import { Recorder } from './Recorder'
 import { RuntimeNotice } from './RuntimeNotice'
-import type { ClinicalData, Consultation, ConsultationTemplate, Document, ExportResult, Status, Transcript, User } from './types'
+import { TranscriptPanel } from './TranscriptPanel'
+import type { SourceSelection } from './SourceEvidence'
+import type { ClinicalData, Consultation, ConsultationTemplate, Document, ExportResult, Status, Transcript, TranscriptTextChange, User } from './types'
 import { Button } from './ui'
-import { cn, formatDate, formatTime, statusLabel } from './utils'
+import { cn, formatDate, statusLabel } from './utils'
 
 const queryClient = new QueryClient({ defaultOptions: { queries: { retry: (count, error) => !(error instanceof ApiError && [401, 403, 404].includes(error.status)) && count < 1, staleTime: 15_000, refetchOnWindowFocus: false } } })
 const hasTranscript = (status?: Status) => Boolean(status && ['TRANSCRIBED', 'AI_GENERATED', 'REVIEWED', 'APPROVED', 'SENT_TO_MIS'].includes(status))
 const hasDocument = (status?: Status) => Boolean(status && ['AI_GENERATED', 'REVIEWED', 'APPROVED', 'SENT_TO_MIS'].includes(status))
+const documentKey = (id: string, revision: number | null | undefined) => ['document', id, revision] as const
+const transcriptKey = (id: string, revision: number | null | undefined) => ['transcript', id, revision] as const
 
 function Mark({ small = false }: { small?: boolean }) {
   return <div className={cn('brand-mark', small && 'brand-mark-small')}><Stethoscope size={small ? 18 : 23} strokeWidth={2.2} /></div>
 }
 
 function StatusBadge({ status }: { status: Status }) {
   return <span className={cn('status-badge', `status-${status.toLowerCase()}`)}><span className="badge-dot" />{statusLabel[status]}</span>
 }
 
 function Login({ onLogin, demo, externalAI, error }: { onLogin: (username: string, password: string) => Promise<void>; demo: boolean; externalAI: boolean; error: string }) {
@@ -47,126 +54,149 @@
 }
 
 function Stepper({ status }: { status: Status }) {
   const steps = [
     { label: 'Создана', icon: FileText }, { label: 'Аудио', icon: AudioLines }, { label: 'Текст', icon: FileClock }, { label: 'Черновик', icon: Sparkles }, { label: 'Проверка', icon: ClipboardCheck }, { label: 'Готово', icon: Check },
   ]
   const position: Record<Status, number> = { CREATED: 0, RECORDING: 1, PROCESSING: 1, TRANSCRIBED: 2, AI_GENERATED: 3, REVIEWED: 4, APPROVED: 5, SENT_TO_MIS: 5, FAILED: 1 }
   return <div className="stepper" aria-label="Этапы консультации">{steps.map((step, index) => <div key={step.label} className={cn('step', index < position[status] && 'done', index === position[status] && 'current')}><div className="step-icon"><step.icon size={16} /></div><span>{step.label}</span></div>)}</div>
 }
 
-function TranscriptPanel({ transcript }: { transcript: Transcript }) {
-  const [view, setView] = useState<'segments' | 'normalized' | 'masked'>('segments')
-  return <div className="transcript-panel"><div className="panel-heading"><div className="heading-icon"><AudioLines size={20} /></div><div><p className="eyebrow">РАЗГОВОР</p><h2>Транскрипция</h2></div></div><div className="transcript-meta"><span><Clock3 size={14} /> {formatTime(transcript.duration_seconds)}</span><span>{transcript.language?.toUpperCase() || 'RU'}</span><span>{transcript.stt_model}</span></div><div className="view-tabs" role="tablist" aria-label="Вид транскрипции"><button role="tab" aria-selected={view === 'segments'} onClick={() => setView('segments')}>Разговор</button><button role="tab" aria-selected={view === 'normalized'} onClick={() => setView('normalized')}>Текст</button><button role="tab" aria-selected={view === 'masked'} onClick={() => setView('masked')}>Обезличено</button></div><div className="transcript-scroll">{view === 'segments' ? (transcript.segments.length ? transcript.segments.map((segment, index) => <div className="segment" key={`${segment.start}-${index}`}><span className="segment-time">{formatTime(segment.start)}</span><div><span className="segment-speaker">{segment.speaker || 'Участник разговора'}</span><p>{segment.text}</p></div></div>) : <p className="transcript-prose">{transcript.raw_text || 'Текст не распознан.'}</p>) : <p className="transcript-prose whitespace-pre-wrap">{view === 'normalized' ? transcript.normalized_text : transcript.masked_text}</p>}</div>{view === 'masked' && <div className="privacy-footer"><ShieldCheck size={16} /> Во внешнюю модель передаётся только обезличенный текст.</div>}</div>
-}
-
 function AuditPanel({ id }: { id: string }) {
   const [open, setOpen] = useState(false)
   const audit = useQuery({ queryKey: ['audit', id], queryFn: () => api.audit(id), enabled: open })
   return <section className="audit-panel"><button className="audit-toggle" onClick={() => setOpen(value => !value)} aria-expanded={open}><span><History size={18} /> История правок</span><span>{open ? 'Скрыть' : 'Показать'} <ChevronRight size={16} className={open ? 'rotate-90' : ''} /></span></button>{open && <div className="audit-content">{audit.isLoading ? <p>Загружаем изменения…</p> : audit.isError ? <p role="alert" className="action-error">Не удалось загрузить историю.</p> : audit.data?.length ? audit.data.map(entry => <div className="audit-row" key={entry.id}><div><strong>{entry.field}</strong><span>{formatDate(entry.created_at)}</span></div><span className={entry.changed ? 'changed-label' : 'unchanged-label'}>{entry.changed ? 'Изменено врачом' : 'Без изменений'}</span>{entry.changed && <div className="audit-values"><div><small>ИИ</small><p>{JSON.stringify(entry.ai_value)}</p></div><ArrowRight size={15} /><div><small>Врач</small><p>{JSON.stringify(entry.doctor_value)}</p></div></div>}</div>) : <p>Правок пока нет.</p>}</div>}</section>
 }
 
 function Workspace({ user, demo, externalAI, onLogout }: { user: User; demo: boolean; externalAI: boolean; onLogout: () => void }) {
   const client = useQueryClient()
   const consultations = useQuery({ queryKey: ['consultations'], queryFn: api.consultations })
   const templates = useQuery({ queryKey: ['templates'], queryFn: api.templates })
   const [selectedId, setSelectedId] = useState<string | null>(() => new URLSearchParams(window.location.search).get('consultation'))
   const [menuOpen, setMenuOpen] = useState(false)
   const [dirty, setDirty] = useState(false)
+  const [transcriptDirty, setTranscriptDirty] = useState(false)
   const [recordingActive, setRecordingActive] = useState(false)
   const [busy, setBusy] = useState(false)
+  const [processingPending, setProcessingPending] = useState(false)
   const [error, setError] = useState('')
   const [exportResult, setExportResult] = useState<ExportResult | null>(null)
   const [regenerationRevision, setRegenerationRevision] = useState(0)
+  const [selection, setSelection] = useState<SourceSelection | null>(null)
+  const [previewOpen, setPreviewOpen] = useState(false)
+  const [latestEdit, setLatestEdit] = useState<{ id: string; revision: number } | null>(null)
   const selectConsultation = useCallback((id: string) => {
     setSelectedId(id)
     const url = new URL(window.location.href)
     url.searchParams.set('consultation', id)
     window.history.replaceState(null, '', url)
   }, [])
   useEffect(() => {
     if (!consultations.data) return
     if ((!selectedId || !consultations.data.some(item => item.id === selectedId)) && consultations.data.length) selectConsultation(consultations.data[0].id)
     else if (selectedId && consultations.data.length === 0) {
       setSelectedId(null)
       const url = new URL(window.location.href)
       url.searchParams.delete('consultation')
       window.history.replaceState(null, '', url)
     }
   }, [selectedId, consultations.data, selectConsultation])
-  const consultation = useQuery({ queryKey: ['consultation', selectedId], queryFn: () => api.consultation(selectedId!), enabled: Boolean(selectedId), refetchInterval: query => query.state.data?.status === 'PROCESSING' ? 2000 : false })
-  const status = consultation.data?.status
+  const consultation = useQuery({ queryKey: ['consultation', selectedId], queryFn: () => api.consultation(selectedId!), enabled: Boolean(selectedId), refetchInterval: query => processingPending || query.state.data?.status === 'PROCESSING' ? 1500 : false })
+  const current = consultation.data && latestEdit?.id === selectedId && (consultation.data.transcript_revision ?? 0) < latestEdit.revision
+    ? { ...consultation.data, status: 'TRANSCRIBED' as const, transcript_revision: latestEdit.revision } : consultation.data
+  const status = current?.status
   useEffect(() => { if (status) void client.invalidateQueries({ queryKey: ['consultations'] }) }, [status, client])
-  const template = templates.data?.find(item => item.id === consultation.data?.template_id)
-  const transcript = useQuery({ queryKey: ['transcript', selectedId], queryFn: () => api.transcript(selectedId!), enabled: Boolean(selectedId && (hasTranscript(status) || status === 'FAILED')) })
-  const document = useQuery({ queryKey: ['document', selectedId], queryFn: () => api.document(selectedId!), enabled: Boolean(selectedId && hasDocument(status)) })
+  const template = templates.data?.find(item => item.id === current?.template_id)
+  const transcript = useQuery({ queryKey: transcriptKey(selectedId ?? '', current?.transcript_revision), queryFn: () => api.transcript(selectedId!), enabled: Boolean(selectedId && (hasTranscript(status) || status === 'FAILED' || (status === 'PROCESSING' && current?.transcript_revision !== null))) })
+  const document = useQuery({ queryKey: documentKey(selectedId ?? '', current?.transcript_revision), queryFn: () => api.document(selectedId!), enabled: Boolean(selectedId && hasDocument(status)) })
+  const freshDocument = Boolean(document.data && hasDocument(status) && document.data.source_transcript_revision === (current?.transcript_revision ?? null) && (!transcript.data || current?.transcript_revision === null || transcript.data.revision === current?.transcript_revision))
+  const visibleDocument = freshDocument ? document.data : null
   useEffect(() => {
-    if (!dirty && !recordingActive && !busy) return
+    if (!dirty && !transcriptDirty && !recordingActive && !busy) return
     const preventLeave = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
     window.addEventListener('beforeunload', preventLeave)
     return () => window.removeEventListener('beforeunload', preventLeave)
-  }, [dirty, recordingActive, busy])
+  }, [dirty, transcriptDirty, recordingActive, busy])
 
   const refreshSummary = useCallback(async (summary: Consultation) => {
     client.setQueryData(['consultation', summary.id], summary)
     await client.invalidateQueries({ queryKey: ['consultations'] })
   }, [client])
   function choose(id: string) {
     if (id === selectedId) return
     if (recordingActive) { setError('Завершите запись или загрузку перед сменой консультации.'); return }
-    if (dirty && !window.confirm('Есть несохранённые изменения. Перейти к другой консультации и потерять их?')) return
-    setError(''); setDirty(false); setExportResult(null); selectConsultation(id)
+    if ((dirty || transcriptDirty) && !window.confirm('Есть несохранённые изменения. Перейти к другой консультации и потерять их?')) return
+    setError(''); setDirty(false); setTranscriptDirty(false); setSelection(null); setPreviewOpen(false); setExportResult(null); selectConsultation(id)
   }
   async function create(externalId: string, templateId: string) {
     if (recordingActive || busy) throw new Error('Завершите запись или обработку перед созданием консультации.')
-    if (dirty && !window.confirm('Есть несохранённые изменения. Создать консультацию и потерять их?')) throw new Error('Создание отменено: сохраните текущие изменения.')
-    const item = await api.create(externalId, templateId); await refreshSummary(item); selectConsultation(item.id); setDirty(false); setError('')
+    if ((dirty || transcriptDirty) && !window.confirm('Есть несохранённые изменения. Создать консультацию и потерять их?')) throw new Error('Создание отменено: сохраните текущие изменения.')
+    const item = await api.create(externalId, templateId); await refreshSummary(item); setSelection(null); setPreviewOpen(false); selectConsultation(item.id); setDirty(false); setTranscriptDirty(false); setError('')
   }
-  async function act(task: () => Promise<void>) { setError(''); setBusy(true); try { await task() } catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось выполнить действие') } finally { setBusy(false) } }
+  async function act(task: () => Promise<void>, poll = false) { setError(''); setBusy(true); if (poll) setProcessingPending(true); try { await task() } catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось выполнить действие') } finally { setBusy(false); if (poll) setProcessingPending(false) } }
   async function beginRecording() { if (!selectedId) return; const updated = await api.beginRecording(selectedId); await refreshSummary(updated) }
   async function upload(file: File) { if (!selectedId) return; const updated = await api.upload(selectedId, file); await refreshSummary(updated) }
-  async function transcribe() { if (!selectedId) return; await act(async () => { await api.transcribe(selectedId); client.invalidateQueries({ queryKey: ['transcript', selectedId] }); const updated = await api.consultation(selectedId); await refreshSummary(updated) }) }
-  async function useDemo() { if (!selectedId) return; await act(async () => { await api.demo(selectedId); client.invalidateQueries({ queryKey: ['transcript', selectedId] }); const updated = await api.consultation(selectedId); await refreshSummary(updated) }) }
-  async function generate() { if (!selectedId) return; if (dirty && !window.confirm('Черновик содержит несохранённые изменения. Создать заново и потерять их?')) return; await act(async () => { const next = await api.generate(selectedId); client.setQueryData(['document', selectedId], next); setRegenerationRevision(value => value + 1); const updated = await api.consultation(selectedId); await refreshSummary(updated); setDirty(false) }) }
-  async function save(data: ClinicalData, version: number): Promise<Document> { if (!selectedId) throw new Error('Выберите консультацию'); const next = await api.save(selectedId, data, version); client.setQueryData(['document', selectedId], next); const updated = await api.consultation(selectedId); await refreshSummary(updated); client.invalidateQueries({ queryKey: ['audit', selectedId] }); return next }
-  async function reloadDocument(): Promise<Document> { if (!selectedId) throw new Error('Выберите консультацию'); const next = await api.document(selectedId); client.setQueryData(['document', selectedId], next); return next }
+  async function transcribe() { if (!selectedId) return; await act(async () => { await api.transcribe(selectedId); void client.invalidateQueries({ queryKey: ['transcript', selectedId] }); const updated = await api.consultation(selectedId); await refreshSummary(updated) }, true) }
+  async function useDemo() { if (!selectedId) return; await act(async () => { await api.demo(selectedId); void client.invalidateQueries({ queryKey: ['transcript', selectedId] }); const updated = await api.consultation(selectedId); await refreshSummary(updated) }, true) }
+  async function generate() { if (!selectedId) return; if (dirty && !window.confirm('Черновик содержит несохранённые изменения. Создать заново и потерять их?')) return; await act(async () => { const next = await api.generate(selectedId); client.setQueryData(documentKey(selectedId, next.source_transcript_revision), next); setRegenerationRevision(value => value + 1); const updated = await api.consultation(selectedId); await refreshSummary(updated); setDirty(false) }, true) }
+  async function save(data: ClinicalData, version: number): Promise<Document> { if (!selectedId) throw new Error('Выберите консультацию'); const next = await api.save(selectedId, data, version); client.setQueryData(documentKey(selectedId, next.source_transcript_revision), next); const updated = await api.consultation(selectedId); await refreshSummary(updated); void client.invalidateQueries({ queryKey: ['audit', selectedId] }); return next }
+  async function reloadDocument(): Promise<Document> { if (!selectedId) throw new Error('Выберите консультацию'); const next = await api.document(selectedId); client.setQueryData(documentKey(selectedId, next.source_transcript_revision), next); return next }
+  async function reloadTranscript(): Promise<Transcript> { if (!selectedId) throw new Error('Выберите консультацию'); const next = await api.transcript(selectedId); const updated = await api.consultation(selectedId); client.setQueryData(transcriptKey(selectedId, next.revision), next); await refreshSummary(updated); return next }
+  async function saveTranscript(changes: TranscriptTextChange[], expectedRevision: number): Promise<void> {
+    if (!selectedId) throw new Error('Выберите консультацию')
+    if ((hasDocument(status) || dirty) && !window.confirm('Исправление транскрипции сделает текущий черновик недействительным. Несохранённые правки документа будут потеряны. Продолжить?')) throw new Error('Исправление отменено')
+    const id = selectedId
+    const updated = await api.editTranscript(id, expectedRevision, changes)
+    setLatestEdit({ id, revision: updated.revision })
+    client.setQueryData(['consultation', id], (previous: Consultation | undefined) => previous ? { ...previous, status: 'TRANSCRIBED', transcript_revision: updated.revision, error_message: null } : previous)
+    client.setQueryData(transcriptKey(id, updated.revision), updated)
+    await client.cancelQueries({ queryKey: ['document', id] })
+    client.removeQueries({ queryKey: ['document', id] })
+    setSelection(null)
+    setDirty(false)
+    setTranscriptDirty(false)
+    try { await refreshSummary(await api.consultation(id)) } catch { /* optimistic revision remains until next poll */ }
+  }
   async function approve(version: number) { if (!selectedId || dirty) return; const updated = await api.approve(selectedId, version); await refreshSummary(updated) }
   async function exportToMis() { if (!selectedId) return; await act(async () => { const result = await api.sendToMis(selectedId); setExportResult(result); const updated = await api.consultation(selectedId); await refreshSummary(updated) }) }
   async function downloadDocx() { if (!selectedId) return; await act(() => api.downloadDocx(selectedId)) }
-  const current = consultation.data
   const canAudio = status === 'CREATED' || status === 'RECORDING' || (status === 'FAILED' && !transcript.data)
   const canTranscribe = status === 'RECORDING' || (status === 'FAILED' && !transcript.data)
   const canGenerate = status === 'TRANSCRIBED' || status === 'AI_GENERATED' || (status === 'FAILED' && Boolean(transcript.data))
   function safeLogout() {
     if (recordingActive || busy) { setError('Завершите запись или обработку перед выходом.'); return }
-    if (dirty && !window.confirm('Есть несохранённые изменения. Выйти и потерять их?')) return
+    if ((dirty || transcriptDirty) && !window.confirm('Есть несохранённые изменения. Выйти и потерять их?')) return
+    setPreviewOpen(false)
     onLogout()
   }
 
   return <div className="app-shell"><Sidebar consultations={consultations.data ?? []} selectedId={selectedId} onSelect={choose} onCreate={create} templates={templates.data ?? []} templatesLoading={templates.isLoading} templatesError={templates.isError} user={user} onLogout={safeLogout} open={menuOpen} onClose={() => setMenuOpen(false)} /><main className="main"><header className="topbar"><div className="topbar-left"><button className="mobile-menu" aria-label="Открыть меню" onClick={() => setMenuOpen(true)}><Menu size={22} /></button><span className="breadcrumb">Рабочая область</span><ChevronRight size={14} /><strong>Консультации</strong></div><div className="topbar-right"><span className="topbar-security"><ShieldCheck size={15} /> Защищённый доступ</span><span className="topbar-avatar">{user.display_name?.charAt(0).toUpperCase() || 'В'}</span></div></header>
     <div className="main-content"><RuntimeNotice demo={demo} externalAI={externalAI} />
     {consultations.isError && <div role="alert" className="page-error"><CircleAlert size={18} /> Не удалось загрузить консультации. <button onClick={() => void consultations.refetch()}>Повторить</button></div>}
     {consultation.isError && <div role="alert" className="page-error"><CircleAlert size={18} /> Не удалось загрузить выбранную консультацию. <button onClick={() => void consultation.refetch()}>Повторить</button></div>}
     {error && <div role="alert" className="page-error"><CircleAlert size={18} /> {error}<button aria-label="Скрыть ошибку" onClick={() => setError('')}><X size={16} /></button></div>}
     {!selectedId && !consultations.isLoading ? <div className="welcome-empty"><div className="welcome-icon"><FileText size={30} /></div><span className="eyebrow">ВАШЕ РАБОЧЕЕ ПРОСТРАНСТВО</span><h1>Начните с новой консультации</h1><p>Создайте запись пациента, добавьте аудио и получите черновик для проверки.</p><NewConsultationDialog onCreate={create} templates={templates.data ?? []} templatesLoading={templates.isLoading} templatesError={templates.isError} /></div> : !current ? <div className="loading-state">Загружаем консультацию…</div> : <>
-      <div className="page-heading"><div><div className="page-heading-kicker"><span>КОНСУЛЬТАЦИЯ</span><span className="kicker-divider" />{formatDate(current.created_at)}</div><div className="page-title-line"><h1>{current.external_patient_id}</h1><StatusBadge status={current.status} /></div><p>{template?.name || 'Бланк консультации'} · Документ #{current.id.slice(0, 8)} · {status === 'SENT_TO_MIS' ? 'Передан в тестовый МИС' : 'Подготовка листа консультации'}</p></div><div className="heading-actions">{current.approved_at && <span className="approved-date"><Check size={15} /> Подтверждено {formatDate(current.approved_at)}</span>}{(status === 'APPROVED' || status === 'SENT_TO_MIS') && <Button variant="secondary" size="sm" disabled={busy} onClick={downloadDocx}><Download size={15} /> Скачать DOCX</Button>}</div></div>
+      <div className="page-heading"><div><div className="page-heading-kicker"><span>КОНСУЛЬТАЦИЯ</span><span className="kicker-divider" />{formatDate(current.created_at)}</div><div className="page-title-line"><h1>{current.external_patient_id}</h1><StatusBadge status={current.status} /></div><p>{template?.name || 'Бланк консультации'} · Документ #{current.id.slice(0, 8)} · {status === 'SENT_TO_MIS' ? 'Передан в тестовый МИС' : 'Подготовка листа консультации'}</p></div><div className="heading-actions">{current.approved_at && <span className="approved-date"><Check size={15} /> Подтверждено {formatDate(current.approved_at)}</span>}{visibleDocument && (status === 'APPROVED' || status === 'SENT_TO_MIS') && <><Button variant="secondary" size="sm" disabled={busy} onClick={() => setPreviewOpen(true)}>Просмотреть PDF</Button><Button variant="secondary" size="sm" disabled={busy} onClick={downloadDocx}><Download size={15} /> Скачать DOCX</Button></>}</div></div>
       <Stepper status={current.status} />
       {current.status === 'FAILED' && <div className="failure-note"><CircleAlert size={18} /><span>{current.error_message || 'Обработка прервалась. Можно повторить доступный этап.'}</span></div>}
       <div className="workflow-grid"><div className="workflow-left"><section className="workspace-card audio-card"><div className="card-topline"><span>01 / ИСХОДНЫЕ ДАННЫЕ</span><span>{hasTranscript(status) ? 'ГОТОВО' : status === 'PROCESSING' ? 'ОБРАБОТКА' : 'ОЖИДАЕТ'}</span></div><h2>Запись приёма</h2><p className="section-subtitle">Добавьте разговор, чтобы подготовить текст консультации.</p>{canAudio ? <Recorder disabled={busy} onBegin={beginRecording} onRecorded={upload} onActiveChange={setRecordingActive} /> : <div className="audio-complete"><div className="audio-complete-icon">{status === 'PROCESSING' ? <AudioLines size={19} /> : <Check size={19} />}</div><div><strong>{status === 'PROCESSING' ? 'Идёт обработка' : 'Аудио обработано'}</strong><p>{status === 'PROCESSING' ? 'Дождитесь завершения текущего этапа.' : 'Транскрипция готова для дальнейшей работы.'}</p></div></div>}
         {demo && (status === 'CREATED' || status === 'FAILED') && <button className="sample-button" disabled={busy || recordingActive} onClick={useDemo}><FlaskConical size={17} /><span>Использовать синтетический пример</span><ArrowRight size={16} /></button>}
         {canTranscribe && <Button className="mt-4" disabled={busy || recordingActive} onClick={transcribe}><AudioLines size={16} /> {busy ? 'Распознаём…' : 'Транскрибировать аудио'}</Button>}
       </section>
-      {transcript.data && <section className="workspace-card transcript-card"><TranscriptPanel transcript={transcript.data} /></section>}
+      <section className="workspace-card processing-card"><ProcessingPanel runs={current.processing_runs} /></section>
+      {transcript.data && <section className="workspace-card transcript-card"><TranscriptPanel key={selectedId} consultationId={current.id} transcript={transcript.data} editable={Boolean(status && ['TRANSCRIBED', 'AI_GENERATED', 'REVIEWED', 'FAILED'].includes(status))} selection={selection} onSave={saveTranscript} onReload={reloadTranscript} onDirtyChange={setTranscriptDirty} /></section>}
       {hasTranscript(status) && !transcript.data && <section className="workspace-card loading-card">{transcript.isError ? 'Не удалось загрузить транскрипцию.' : 'Загружаем транскрипцию…'}</section>}
-      </div><div className="workflow-right"><section className="workspace-card document-card"><div className="card-topline"><span>02 / КЛИНИЧЕСКИЙ ДОКУМЕНТ</span><span>{status === 'APPROVED' || status === 'SENT_TO_MIS' ? 'ПОДТВЕРЖДЕНО' : status === 'REVIEWED' ? 'ГОТОВО К ПОДТВЕРЖДЕНИЮ' : status === 'AI_GENERATED' ? 'ЧЕРНОВИК ИИ' : 'ОЖИДАЕТ'}</span></div>{document.data && template ? <DocumentEditor key={`${selectedId}-${template.id}`} document={document.data} template={template} status={current.status} busy={busy} regenerationRevision={regenerationRevision} onSave={save} onApprove={approve} onReload={reloadDocument} onDirtyChange={setDirty} /> : <div className="document-empty"><div className="document-empty-icon"><Sparkles size={25} /></div><h2>{template?.name || 'Черновик консультации'}</h2><p>На основе транскрипции система подготовит структурированный лист. Вы сможете проверить и исправить каждый раздел.</p>{canGenerate && !document.data && <Button disabled={busy} onClick={generate}><Sparkles size={16} /> {busy ? 'Подготавливаем…' : 'Сформировать черновик'}</Button>}{!canGenerate && !document.data && <span className="document-empty-hint">Сначала добавьте и транскрибируйте аудио</span>}{document.data && !template && <span className="document-empty-hint">Загружаем бланк консультации…</span>}{document.isError && <p role="alert" className="action-error">Не удалось загрузить документ.</p>}</div>}
-      </section>{document.data && canGenerate && <Button variant="ghost" className="regenerate" disabled={busy} onClick={generate}><Sparkles size={15} /> Сформировать черновик заново</Button>}{document.data && <AuditPanel id={current.id} />}{current.status === 'APPROVED' && <section className="export-card"><div className="export-card-icon"><UploadCloud size={22} /></div><div><h3>Документ подтверждён</h3><p>Отправка в тестовый МИС создаст имитацию экспорта.</p></div><Button disabled={busy} onClick={exportToMis}><UploadCloud size={16} /> Отправить в mock МИС</Button></section>}{current.status === 'SENT_TO_MIS' && <section className="export-card sent"><div className="export-card-icon"><Check size={22} /></div><div><h3>Передано в mock МИС</h3><p>{exportResult?.document_id ? `Тестовый номер документа: ${exportResult.document_id}` : 'Экспорт завершён. Реальная медицинская система не подключена.'}</p></div></section>}</div></div>
+      {transcript.data && <section className="workspace-card privacy-card"><PrivacyPanel transcript={transcript.data} document={visibleDocument ?? null} /></section>}
+      </div><div className="workflow-right"><section className="workspace-card document-card"><div className="card-topline"><span>02 / КЛИНИЧЕСКИЙ ДОКУМЕНТ</span><span>{status === 'APPROVED' || status === 'SENT_TO_MIS' ? 'ПОДТВЕРЖДЕНО' : status === 'REVIEWED' ? 'ГОТОВО К ПОДТВЕРЖДЕНИЮ' : status === 'AI_GENERATED' ? 'ЧЕРНОВИК ИИ' : 'ОЖИДАЕТ'}</span></div>{visibleDocument && template ? <DocumentEditor key={`${selectedId}-${template.id}`} document={visibleDocument} template={template} status={current.status} busy={busy} regenerationRevision={regenerationRevision} onSave={save} onApprove={approve} onReload={reloadDocument} onDirtyChange={setDirty} onSourceSelect={setSelection} /> : <div className="document-empty"><div className="document-empty-icon"><Sparkles size={25} /></div><h2>{template?.name || 'Черновик консультации'}</h2><p>На основе транскрипции система подготовит структурированный лист. Вы сможете проверить и исправить каждый раздел.</p>{canGenerate && !visibleDocument && <Button disabled={busy} onClick={generate}><Sparkles size={16} /> {busy ? 'Подготавливаем…' : 'Сформировать черновик'}</Button>}{!canGenerate && !visibleDocument && <span className="document-empty-hint">Сначала добавьте и транскрибируйте аудио</span>}{visibleDocument && !template && <span className="document-empty-hint">Загружаем бланк консультации…</span>}{document.isError && <p role="alert" className="action-error">Не удалось загрузить документ.</p>}</div>}
+      </section>{visibleDocument && canGenerate && <Button variant="ghost" className="regenerate" disabled={busy} onClick={generate}><Sparkles size={15} /> Сформировать черновик заново</Button>}{visibleDocument && <AuditPanel id={current.id} />}{current.status === 'APPROVED' && <section className="export-card"><div className="export-card-icon"><UploadCloud size={22} /></div><div><h3>Документ подтверждён</h3><p>Отправка в тестовый МИС создаст имитацию экспорта.</p></div><Button disabled={busy} onClick={exportToMis}><UploadCloud size={16} /> Отправить в mock МИС</Button></section>}{current.status === 'SENT_TO_MIS' && <section className="export-card sent"><div className="export-card-icon"><Check size={22} /></div><div><h3>Передано в mock МИС</h3><p>{exportResult?.document_id ? `Тестовый номер документа: ${exportResult.document_id}` : 'Экспорт завершён. Реальная медицинская система не подключена.'}</p></div></section>}</div></div>
     </>}
+    <PdfPreview consultationId={selectedId ?? ''} open={Boolean(previewOpen && selectedId && visibleDocument && (status === 'APPROVED' || status === 'SENT_TO_MIS'))} onClose={() => setPreviewOpen(false)} />
     <footer className="app-footer"><span>MedHub · AI Medical Scribe</span><span>Решение и подтверждение всегда остаётся за врачом</span></footer></div></main></div>
 }
 
 function AuthApp() {
   const [authenticated, setAuthenticated] = useState(hasToken())
   const [loginError, setLoginError] = useState('')
   const health = useQuery({ queryKey: ['health'], queryFn: api.health, retry: false })
   const me = useQuery({ queryKey: ['me'], queryFn: api.me, enabled: authenticated, retry: false })
   useEffect(() => {
     const handleUnauthorized = () => { setAuthenticated(false); queryClient.clear() }

```

## src/DocumentEditor.tsx
```diff
--- /tmp/medhub-p0-snapshots.BPZlzl/task-7-base/src/DocumentEditor.tsx	2026-09-30 14:31:08.592734027 +0500
+++ src/DocumentEditor.tsx	2026-09-30 14:41:50.601632095 +0500
@@ -1,26 +1,53 @@
 import { useEffect, useRef, useState } from 'react'
 import { zodResolver } from '@hookform/resolvers/zod'
 import { useFieldArray, useForm, type Control, type FieldErrors, type UseFormRegister } from 'react-hook-form'
 import { AlertCircle, Check, CheckCheck, FileText, Plus, Save, ShieldCheck, Trash2 } from 'lucide-react'
 import { Button } from './ui'
 import { DiagnosisPicker } from './DiagnosisPicker'
 import { ApiError } from './api'
 import { canApprove, clinicalSchema, clinicalToForm, formToClinical, type ClinicalForm } from './clinical'
-import type { ConsultationTemplate, Document, Status } from './types'
+import { SourceEvidence, type SourceSelection } from './SourceEvidence'
+import type { ClinicalData, ConsultationTemplate, Document, Status } from './types'
 
 type Props = {
   document: Document; template: ConsultationTemplate; status: Status; busy: boolean; regenerationRevision: number;
   onSave: (data: ReturnType<typeof formToClinical>, version: number) => Promise<Document>;
   onApprove: (version: number) => Promise<void>;
   onReload: () => Promise<Document>;
   onDirtyChange: (dirty: boolean) => void;
+  onSourceSelect?: (selection: SourceSelection) => void;
+}
+
+function sourcePaths(data: ClinicalData): string[] {
+  const paths: string[] = []
+  for (const [key, value] of Object.entries(data)) {
+    if (key === 'diagnosis_code' || value == null) continue
+    if (key === 'template_fields') {
+      for (const field of data.template_fields) if (field.value) paths.push(`template_fields/${field.key}`)
+    } else if (key === 'vital_signs') {
+      for (const [name, entry] of Object.entries(data.vital_signs ?? {})) if (entry) paths.push(`vital_signs/${name}`)
+    } else if (Array.isArray(value)) {
+      value.forEach((entry, index) => {
+        if (typeof entry === 'string') paths.push(`${key}/${index}`)
+        else if (entry && typeof entry === 'object') for (const [name, part] of Object.entries(entry)) if (part) paths.push(`${key}/${index}/${name}`)
+      })
+    } else if (value) paths.push(key)
+  }
+  return paths
+}
+
+function pathLabel(path: string, template: ConsultationTemplate): string {
+  if (path.startsWith('template_fields/')) return template.fields.find(field => field.key === path.split('/')[1])?.label ?? path
+  const names: Record<string, string> = { complaints: 'Жалобы', anamnesis_morbi: 'История заболевания', anamnesis_vitae: 'Анамнез жизни', allergies: 'Аллергии', medications: 'Принимаемые препараты', vital_signs: 'Показатели', objective_status: 'Объективный статус', diagnosis: 'Диагноз', recommendations: 'Рекомендации', prescribed_medications: 'Назначенные препараты', additional_notes: 'Дополнительные заметки' }
+  const [root, index, part] = path.split('/')
+  return [names[root] ?? root, index && /^\d+$/.test(index) ? `№${Number(index) + 1}` : index, part].filter(Boolean).join(' · ')
 }
 
 function Field({ label, name, register, multiline = false, disabled = false, hint }: { label: string; name: keyof Pick<ClinicalForm, 'anamnesis_morbi' | 'anamnesis_vitae' | 'objective_status' | 'diagnosis' | 'additional_notes'>; register: UseFormRegister<ClinicalForm>; multiline?: boolean; disabled?: boolean; hint?: string }) {
   const id = `field-${name}`
   return <label htmlFor={id} className="field-label">{label}{hint && <span className="field-hint">{hint}</span>}{multiline ? <textarea id={id} {...register(name)} disabled={disabled} rows={3} className="input resize-y" /> : <input id={id} {...register(name)} disabled={disabled} className="input" />}</label>
 }
 
 type ArrayName = 'complaints' | 'allergies' | 'recommendations'
 function TextList({ name, title, placeholder, control, register, errors, disabled }: { name: ArrayName; title: string; placeholder: string; control: Control<ClinicalForm>; register: UseFormRegister<ClinicalForm>; errors: FieldErrors<ClinicalForm>; disabled: boolean }) {
   const { fields, append, remove } = useFieldArray({ control, name })
@@ -37,21 +64,21 @@
     {fields.length === 0 && <p className="empty-field">Препараты не указаны.</p>}
     {fields.map((field, i) => <div className="med-card" key={field.id}><div className="med-card-head"><span>Препарат {i + 1}</span>{!disabled && <Button aria-label={`Удалить препарат ${i + 1}`} type="button" variant="ghost" size="icon" onClick={() => remove(i)}><Trash2 size={16} /></Button>}</div><div className="grid gap-3 sm:grid-cols-2"><label className="field-label">Название<input aria-label={`${title}: название ${i + 1}`} {...register(`${name}.${i}.name`)} disabled={disabled} className="input" />{errors[name]?.[i]?.name && <span className="field-error">{errors[name]?.[i]?.name?.message}</span>}</label><label className="field-label">Дозировка<input {...register(`${name}.${i}.dosage`)} disabled={disabled} className="input" /></label><label className="field-label">Частота<input {...register(`${name}.${i}.frequency`)} disabled={disabled} className="input" /></label><label className="field-label">Длительность<input {...register(`${name}.${i}.duration`)} disabled={disabled} className="input" /></label></div></div>)}
   </section>
 }
 
 const vitalFields = [
   ['temperature', 'Температура'], ['blood_pressure', 'Давление'], ['heart_rate', 'Пульс'],
   ['respiratory_rate', 'Частота дыхания'], ['oxygen_saturation', 'Сатурация'],
 ] as const
 
-export function DocumentEditor({ document, template, status, busy, regenerationRevision, onSave, onApprove, onReload, onDirtyChange }: Props) {
+export function DocumentEditor({ document, template, status, busy, regenerationRevision, onSave, onApprove, onReload, onDirtyChange, onSourceSelect }: Props) {
   const [version, setVersion] = useState(document.version)
   const lastRegeneration = useRef(regenerationRevision)
   const dirtyRef = useRef(false)
   const [saved, setSaved] = useState(false)
   const [actionError, setActionError] = useState('')
   const [conflict, setConflict] = useState(false)
   const editable = status === 'AI_GENERATED' || status === 'REVIEWED'
   const { register, control, handleSubmit, reset, watch, setValue, formState: { errors, isDirty, isSubmitting } } = useForm<ClinicalForm>({ resolver: zodResolver(clinicalSchema), defaultValues: clinicalToForm(document.data, template.fields) })
   useEffect(() => { if (!dirtyRef.current && document.version !== version) { reset(clinicalToForm(document.data, template.fields)); setVersion(document.version) } }, [document, isDirty, reset, version, template.fields])
   useEffect(() => {
@@ -91,31 +118,36 @@
       dirtyRef.current = false
       setVersion(updated.version)
       setActionError('')
       setConflict(false)
       setSaved(false)
       onDirtyChange(false)
     } catch (error) { setActionError(error instanceof Error ? error.message : 'Не удалось обновить документ') }
   }
 
   const specialty = template.fields.filter(field => !field.clinical_field)
+  const currentData = formToClinical(watch())
+  const paths = sourcePaths(document.ai_generated_data)
   return <div className="document-editor"><div className="panel-heading"><div className="heading-icon"><FileText size={20} /></div><div><p className="eyebrow">Клинический документ</p><h2>{template.name}</h2></div><span className="version-chip">Версия {version}</span></div>
     <div className={`review-note ${editable ? '' : 'review-note-locked'}`}>{editable ? <AlertCircle size={17} /> : <ShieldCheck size={17} />}<span>{status === 'REVIEWED' ? 'Проверка сохранена. Подтвердите документ после финального просмотра.' : editable ? 'ИИ подготовил черновик. Проверьте каждое поле перед подтверждением.' : 'Документ подтверждён врачом. Поля доступны только для просмотра.'}</span></div>
-    <form onSubmit={handleSubmit(save)} noValidate><fieldset disabled={!editable || busy || isSubmitting} className="form-fields">
+    <form aria-label="Клинический документ" onSubmit={handleSubmit(save)} noValidate><fieldset disabled={!editable || busy || isSubmitting} className="form-fields">
       <TextList name="complaints" title="Жалобы" placeholder="Жалоба пациента" control={control} register={register} errors={errors} disabled={!editable || busy} />
       <div className="form-section space-y-4"><h3>Анамнез</h3><Field label="История заболевания" name="anamnesis_morbi" register={register} multiline /><Field label="Анамнез жизни" name="anamnesis_vitae" register={register} multiline /></div>
       <TextList name="allergies" title="Аллергии" placeholder="Указанная аллергия" control={control} register={register} errors={errors} disabled={!editable || busy} />
       <MedicationList name="medications" title="Принимаемые препараты" control={control} register={register} errors={errors} disabled={!editable || busy} />
       <section className="form-section"><h3>Показатели</h3><div className="grid gap-3 sm:grid-cols-2">{vitalFields.map(([name, label]) => <label className="field-label" key={name}>{label}<input {...register(`vital_signs.${name}`)} className="input" placeholder="Не указано" /></label>)}</div></section>
       <div className="form-section space-y-4"><h3>Осмотр и заключение</h3><Field label="Объективный статус" name="objective_status" register={register} multiline /><Field label="Диагноз" name="diagnosis" register={register} multiline hint="Только после проверки врачом" /><input type="hidden" {...register('diagnosis_code')} /><DiagnosisPicker value={watch('diagnosis_code')} onChange={code => setValue('diagnosis_code', code, { shouldDirty: true, shouldValidate: true })} disabled={!editable || busy || isSubmitting} /></div>
       <TextList name="recommendations" title="Рекомендации" placeholder="Рекомендация" control={control} register={register} errors={errors} disabled={!editable || busy} />
       <MedicationList name="prescribed_medications" title="Назначенные препараты" control={control} register={register} errors={errors} disabled={!editable || busy} />
       <div className="form-section"><Field label="Дополнительные заметки" name="additional_notes" register={register} multiline /></div>
       {specialty.length > 0 && <section className="form-section specialty-section"><div className="specialty-intro"><h3>Поля выбранного бланка</h3><p>Заполняйте только сведения, прозвучавшие на приёме. Пустое поле останется «Не указано».</p></div>{specialty.map((field, index) => <label className="field-label specialty-field" key={field.key}>{field.label}<span className="specialty-section-name">{field.section}</span><span className="field-hint">{field.prompt}</span><input type="hidden" {...register(`template_fields.${index}.key`)} /><textarea rows={2} className="input resize-y" aria-label={field.label} {...register(`template_fields.${index}.value`)} placeholder="Не указано" /></label>)}</section>}
     </fieldset>
+    <section className="evidence-section" aria-label="Источники AI-версии"><h3>Источники AI-версии</h3><p>Фрагменты показывают происхождение AI-черновика, а не медицинскую достоверность.</p>
+      {paths.length ? paths.map(path => <div className="evidence-field" key={path}><h4>{pathLabel(path, template)}</h4><SourceEvidence fieldPath={path} aiData={document.ai_generated_data} currentData={currentData} evidence={document.evidence} onSelect={onSourceSelect ?? (() => {})} /></div>) : <p>Источники для этой генерации не записаны.</p>}
+    </section>
     {actionError && <div role="alert" className="action-error">{actionError}{conflict && <><span> Версия документа изменилась. Ваши правки остались в форме.</span><Button type="button" variant="secondary" size="sm" className="mt-2" onClick={reload}>Загрузить актуальную версию</Button></>}</div>}
     {editable && saved && !isDirty && <p className="saved-note"><Check size={15} /> Изменения сохранены. Теперь документ можно подтвердить.</p>}
     {editable && <div className="editor-actions"><Button type="submit" disabled={busy || isSubmitting} variant="secondary"><Save size={16} /> {isSubmitting ? 'Сохраняем…' : 'Сохранить проверку'}</Button><Button type="button" onClick={approve} disabled={!canApprove(status, isDirty, version) || busy || isSubmitting} title={isDirty ? 'Сначала сохраните изменения' : undefined}><CheckCheck size={17} /> Подтвердить</Button></div>}
     {editable && isDirty && <p className="unsaved-note">Есть несохранённые изменения. Сохраните их перед подтверждением.</p>}
     </form>
   </div>
 }

```

## src/DocumentEditor.test.tsx
```diff
--- /tmp/medhub-p0-snapshots.BPZlzl/task-7-base/src/DocumentEditor.test.tsx	2026-09-30 14:31:08.592791776 +0500
+++ src/DocumentEditor.test.tsx	2026-09-30 14:40:50.563845063 +0500
@@ -6,20 +6,34 @@
 import type { ClinicalData, ConsultationTemplate, Document } from './types'
 
 const template: ConsultationTemplate = { id: 'cardiologist', name: 'Осмотр кардиолога', fields: [
   { key: 'rhythm', label: 'Ритм сердца', prompt: 'Ритм сердца, частота и особенности', section: 'Осмотр' },
   { key: 'diagnosis', label: 'Диагноз', prompt: 'Диагноз', section: 'Заключение', clinical_field: 'diagnosis' },
 ] }
 const document: Document = { id: 'doc-1', consultation_id: 'c-1', ai_generated_data: emptyClinicalData, doctor_approved_data: null, data: emptyClinicalData, llm_provider: 'demo', llm_model: 'demo', updated_at: '2026-09-30T00:00:00Z', version: 1, source_transcript_revision: 1, source_masked_text: null, evidence: [] }
 afterEach(() => { cleanup(); vi.unstubAllGlobals() })
 
 describe('doctor document editor', () => {
+  it('keeps AI evidence selectable on an approved read-only document', () => {
+    const onSourceSelect = vi.fn()
+    const ai = { ...emptyClinicalData, diagnosis: 'Исходный диагноз' }
+    const approved: Document = { ...document, ai_generated_data: ai, data: { ...ai, diagnosis: 'Диагноз врача' }, doctor_approved_data: { ...ai, diagnosis: 'Диагноз врача' }, evidence: [{ field_path: 'diagnosis', segment_id: 'seg-000001', quote: 'Кашель три дня', transcript_revision: 1, start: 4, end: 6 }] }
+    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
+    render(<QueryClientProvider client={client}><DocumentEditor document={approved} template={template} status="APPROVED" busy={false} regenerationRevision={0} onSave={vi.fn()} onApprove={vi.fn()} onReload={vi.fn()} onDirtyChange={vi.fn()} onSourceSelect={onSourceSelect} /></QueryClientProvider>)
+    expect(screen.getByRole('form', { name: /документ/i })).toBeVisible()
+    expect(screen.getByText(/Источник AI-версии/)).toBeVisible()
+    const source = screen.getByRole('button', { name: /Кашель три дня/ })
+    expect(source).toBeEnabled()
+    fireEvent.click(source)
+    expect(onSourceSelect).toHaveBeenCalledWith({ segmentId: 'seg-000001', start: 4, quote: 'Кашель три дня' })
+  })
+
   it('saves specialty fields with medication and vitals, then enables approval of saved version', async () => {
     let saved: ClinicalData | null = null
     const onSave = vi.fn(async (data: ClinicalData, version: number) => { expect(version).toBe(1); saved = data; return { ...document, data, version: 2 } })
     const onApprove = vi.fn(async (_version: number) => undefined)
     const props = { document, template, status: 'AI_GENERATED' as const, busy: false, regenerationRevision: 0, onSave, onApprove, onReload: vi.fn(async () => document), onDirtyChange: vi.fn() }
     const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
     vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ items: [{ code: 'I10', name_ru: 'Эссенциальная гипертензия', name_kz: null }], total: 1 }), { status: 200, headers: { 'Content-Type': 'application/json' } })))
     const view = render(<QueryClientProvider client={client}><DocumentEditor {...props} /></QueryClientProvider>)
     expect(screen.queryAllByRole('textbox', { name: /^Диагноз/ })).toHaveLength(1)
     fireEvent.click(within(screen.getByText('Жалобы').closest('section')!).getByRole('button', { name: 'Добавить' }))

```

## src/styles.css
```diff
--- /tmp/medhub-p0-snapshots.BPZlzl/task-7-base/src/styles.css	2026-09-30 14:31:08.592839065 +0500
+++ src/styles.css	2026-09-30 14:48:28.317904166 +0500
@@ -24,11 +24,38 @@
 .dialog-overlay{position:fixed;inset:0;background:#0e2e3c78;z-index:70}.dialog-content{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);width:min(calc(100vw - 32px),460px);z-index:80;border-radius:20px;background:#fff;box-shadow:0 25px 90px #071e3060;padding:27px}.dialog-head{display:flex;justify-content:space-between;align-items:center}.dialog-title{font-size:22px;font-weight:800;letter-spacing:-.04em;margin-top:20px}.dialog-desc{color:#7e959b;font-size:12px;line-height:1.7;margin-top:7px}
 .dialog-content select.input{appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' fill='none' stroke='%23759198' stroke-width='2' viewBox='0 0 24 24'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 12px center;padding-right:34px}.heading-actions{display:flex;align-items:center;gap:11px;flex-wrap:wrap}.welcome-empty{min-height:460px;display:flex;align-items:center;justify-content:center;flex-direction:column;text-align:center;background:#fff;border:1px solid #e7efed;border-radius:16px;padding:35px}.welcome-icon{display:grid;place-items:center;width:72px;height:72px;color:#087e83;background:#eaf7f2;border-radius:21px;margin-bottom:24px}.welcome-empty h1{font-size:26px;letter-spacing:-.04em;margin:8px 0}.welcome-empty p{color:#8ba0a5;font-size:12px;line-height:1.7;margin-bottom:26px}.welcome-empty .new-consultation{width:auto;padding:0 18px}.specialty-intro p{font-size:10px;line-height:1.6;color:#8ba0a4;margin:-4px 0 13px}.specialty-field{padding:12px 0;border-top:1px solid #edf1f0}.specialty-field .field-hint{font-weight:500;line-height:1.5;margin:5px 0}.specialty-section-name{float:right;color:#6f9c90;background:#edf7f2;padding:3px 7px;border-radius:6px;font-size:9px}.specialty-field .input{margin-top:9px}
 .diagnosis-picker{position:relative}.diagnosis-label-row{display:flex;align-items:center;justify-content:space-between;gap:8px}.diagnosis-selected{display:inline-flex;align-items:center;gap:3px;background:#e8f6ef;color:#328663;border-radius:7px;padding:2px 5px 2px 8px;font-size:10px;font-weight:800}.diagnosis-selected button{height:19px;width:19px}.diagnosis-search{position:relative;margin-top:7px}.diagnosis-search svg{position:absolute;top:13px;left:12px;color:#9badb1}.diagnosis-search input{width:100%;height:43px;border:1px solid #dce6e5;border-radius:10px;padding:0 12px 0 38px;color:#173848;font-size:12px}.diagnosis-search input:focus{border-color:#087e83}.diagnosis-help{font-size:10px;color:#91a4a8;margin:6px 0 0}.diagnosis-results{max-height:245px;overflow-y:auto;background:#fff;border:1px solid #e0e9e6;border-radius:10px;box-shadow:0 13px 26px #163c4a16;margin-top:7px}.diagnosis-results>p{margin:0;padding:14px;color:#879ba0;font-size:11px}.diagnosis-results button{display:flex;gap:9px;align-items:flex-start;text-align:left;width:100%;background:#fff;border:0;border-bottom:1px solid #eef2f1;padding:10px 12px;color:#4d6973;font-size:11px}.diagnosis-results button:hover,.diagnosis-results button[aria-selected=true]{background:#eff8f5}.diagnosis-results button strong{color:#087e83;min-width:41px}
 
 @media(max-width:1250px){.workflow-grid{grid-template-columns:minmax(300px,.83fr) minmax(390px,1.17fr)}.step{gap:5px}.step span{font-size:9px}.step-icon{width:27px;height:27px}.main-content{padding:24px}.topbar{padding:0 24px}}
 @media(max-width:1050px){.sidebar{width:240px;flex-basis:240px}.workflow-grid{grid-template-columns:1fr}.workflow-left{grid-template-columns:1fr 1fr;align-items:start}.transcript-scroll{max-height:410px}}
 @media(max-width:800px){.sidebar{position:fixed;left:0;top:0;bottom:0;transform:translateX(-100%);transition:transform .22s}.sidebar.show{transform:translateX(0)}.sidebar-scrim.show{display:block;position:fixed;inset:0;background:#0e273b77;z-index:25}.sidebar-close,.mobile-menu{display:grid;place-items:center;border:0;background:transparent;color:#54727c}.sidebar-close{margin-left:auto}.topbar{height:62px}.main-content{padding:20px}.login-layout{grid-template-columns:1fr;gap:25px;padding:28px 20px}.login-intro{height:auto}.login-copy{padding:40px 0 0}.login-copy h1{font-size:45px;margin:18px 0}.hero-lines{margin-top:20px}.login-foot{display:none}.login-card-wrap{max-width:520px;margin-bottom:30px}.decor-one{right:-360px}.workflow-left{grid-template-columns:1fr 1fr}}
 @media(max-width:640px){.main-content{padding:16px 14px}.topbar{padding:0 15px}.topbar-security{display:none}.demo-banner{align-items:start}.demo-pill{display:none}.page-heading{align-items:start}.page-title-line h1{font-size:26px}.approved-date{display:none}.stepper{overflow-x:auto;display:flex;padding:13px 8px}.step{flex:0 0 80px;flex-direction:column;align-items:center;text-align:center;gap:5px}.step:not(:last-child)::after{display:none}.workflow-left{grid-template-columns:1fr}.audio-card,.document-card{padding:16px}.recording-box{align-items:flex-start}.recording-orb{width:44px;height:44px;box-shadow:none}.recording-orb svg{width:22px}.recording-box{padding:14px;gap:13px}.recording-content>div:last-child{margin-top:13px}.recording-content button{font-size:11px;padding:0 10px}.app-footer{flex-direction:column}.export-card{flex-wrap:wrap}.export-card button{width:100%}.login-copy h1{font-size:39px}.login-copy>p{font-size:13px}.hero-lines div{font-size:10px;padding:9px}.login-card{padding:27px}.login-card h2{font-size:25px}}
 :root{font-family:'Noto Sans','Segoe UI',Arial,sans-serif}.segment-time{font-family:'Noto Sans','Segoe UI',Arial,sans-serif}
 .form-fields,.form-fields .form-section,.form-fields .med-card,.form-fields .field-label{min-width:0;max-width:100%}.form-fields .input,.form-fields input,.form-fields textarea{min-width:0;max-width:100%}.form-section-head{min-width:0}.form-section-head h3{min-width:0;overflow-wrap:anywhere}.form-section-head button{flex:none}.review-note-locked{background:#eef8f1;border-color:#d9eadf;color:#418967}
+
+.whitespace-pre-wrap{white-space:pre-wrap;overflow-wrap:anywhere}
+.workflow-left>*,.workflow-right>*,.document-editor,.transcript-panel,.evidence-section,.evidence-field,.processing-panel,.privacy-panel{min-width:0;overflow-wrap:anywhere}
+.processing-card,.privacy-card{padding:20px;color:#4b6670;font-size:12px;line-height:1.6}
+.processing-panel h2,.privacy-panel h2{font-size:15px;color:#294b58;margin:0 0 10px}
+.processing-run{border-top:1px solid #e7efed;padding-top:12px;margin-top:12px}
+.processing-run h3,.privacy-panel h3{font-size:12px;color:#315563;margin:0 0 8px}
+.processing-stages,.privacy-panel ul{padding-left:20px;margin:8px 0}
+.processing-stages li{padding:5px 0;display:flex;flex-wrap:wrap;gap:6px 12px;justify-content:space-between}
+.processing-stages li span:first-child{flex:1 1 150px}
+.privacy-panel p{margin:7px 0}
+.transcript-actions{display:flex;gap:9px;flex-wrap:wrap;padding:12px 22px 18px}
+.selected-source{display:grid;gap:4px;margin:0 22px 8px;padding:11px;border:1px solid #cfe9e2;border-radius:9px;background:#f0faf6;color:#397c70;font-size:11px}
+.selected-source q{color:#385b66;white-space:pre-wrap;overflow-wrap:anywhere}
+.transcript-panel audio{display:block;width:calc(100% - 44px);margin:8px 22px 12px}
+.segment.selected{background:#f0faf6;border-radius:9px;padding:9px}
+.segment>div{min-width:0}.segment p,.transcript-prose,.specialty-field .field-hint{overflow-wrap:anywhere;white-space:pre-wrap}
+.evidence-section{border-top:1px solid #edf1f0;padding:18px 0 4px;margin-top:12px}
+.evidence-section h3{font-size:12px;color:#2a4e5c;margin:0 0 6px}
+.evidence-section>p{font-size:10px;color:#82979d}
+.evidence-field{border-top:1px solid #eef3f1;padding:11px 0}
+.evidence-field h4{font-size:11px;color:#345662;margin:0 0 5px}
+.source-evidence{font-size:10px;color:#69848b}
+.source-evidence p{margin:4px 0;white-space:pre-wrap;overflow-wrap:anywhere}
+.source-quote{display:flex;gap:8px;align-items:flex-start;text-align:left;width:100%;padding:8px 10px;margin-top:6px;border:1px solid #d9eae6;border-radius:8px;background:#f5fbf8;color:#316e67;font-size:10px}
+.source-quote q{flex:1;white-space:pre-wrap;overflow-wrap:anywhere}
+@media(max-width:640px){.page-heading{flex-wrap:wrap}.heading-actions{width:100%}.heading-actions button{flex:1 1 auto}.processing-card,.privacy-card{padding:16px}.selected-source{margin-left:16px;margin-right:16px}.transcript-actions{padding-left:16px;padding-right:16px}}
 .diagnosis-readonly{margin-top:7px;border:1px solid #e1e9e6;border-radius:10px;background:#f7f9f8;padding:11px 13px;color:#56717b;font-size:12px}

```
