# Task7 fix round1 re-review

Read task-7-review-verdict.md for3Importantfindings, task-7-report.md appendedfixevidence, and re-review-prompt.md. Focus fixes and directboundaries only. Report RED4fail/13pass -> focused17/full61/build0; Task9 browserrerun pending. Base /tmp/.../task-7-fix-base. No Git.

## src/TranscriptPanel.tsx
```diff
--- /tmp/medhub-p0-snapshots.BPZlzl/task-7-fix-base/src/TranscriptPanel.tsx	2026-09-30 14:54:04.316200062 +0500
+++ src/TranscriptPanel.tsx	2026-09-30 14:57:59.152533922 +0500
@@ -16,29 +16,38 @@
   const [view, setView] = useState<'segments' | 'normalized' | 'masked'>('segments')
   const [editing, setEditing] = useState(false)
   const [draft, setDraft] = useState(() => segmentDraft(transcript))
   const [saving, setSaving] = useState(false)
   const [error, setError] = useState('')
   const [conflict, setConflict] = useState(false)
   const [audioUrl, setAudioUrl] = useState<string | null>(null)
   const [audioError, setAudioError] = useState(false)
   const audioRef = useRef<HTMLAudioElement>(null)
   const [loadedTranscript, setLoadedTranscript] = useState(transcript)
-  const dirty = transcript.segments.some(segment => (draft[segment.id] ?? segment.text) !== segment.text)
+  const loadedConsultationId = useRef(consultationId)
+  const dirty = loadedTranscript.segments.some(segment => (draft[segment.id] ?? segment.text) !== segment.text)
 
   useEffect(() => {
+    if (loadedConsultationId.current === consultationId && loadedTranscript.revision === transcript.revision) return
+    if (loadedConsultationId.current === consultationId && saving) return
+    if (loadedConsultationId.current === consultationId && editing && dirty) {
+      setConflict(true)
+      setError('Транскрипция обновилась.')
+      return
+    }
+    loadedConsultationId.current = consultationId
     setDraft(segmentDraft(transcript))
     setLoadedTranscript(transcript)
     setEditing(false)
     setError('')
     setConflict(false)
-  }, [consultationId, transcript.revision])
+  }, [consultationId, transcript, loadedTranscript.revision, saving, editing, dirty])
   useEffect(() => { onDirtyChange(editing && dirty) }, [editing, dirty, onDirtyChange])
   useEffect(() => {
     if (!selection || !transcript.audio_available) return
     let active = true
     let url: string | null = null
     const controller = new AbortController()
     setAudioError(false)
     void api.audio(consultationId, controller.signal).then(blob => {
       if (!active) return
       url = URL.createObjectURL(blob)
@@ -50,30 +59,31 @@
       active = false
       controller.abort()
       if (url) URL.revokeObjectURL(url)
       setAudioUrl(null)
     }
   }, [consultationId, Boolean(selection), transcript.audio_available])
   useEffect(() => {
     if (selection && audioRef.current && audioRef.current.readyState >= 1) audioRef.current.currentTime = selection.start
   }, [selection, audioUrl])
 
-  const changes = transcript.segments.filter(segment => (draft[segment.id] ?? segment.text) !== segment.text)
+  const visible = loadedTranscript.revision === transcript.revision ? transcript : loadedTranscript
+  const changes = visible.segments.filter(segment => (draft[segment.id] ?? segment.text) !== segment.text)
     .map(segment => ({ segment_id: segment.id, text: draft[segment.id] }))
 
   async function save() {
     if (!changes.length) return
     setSaving(true)
     setError('')
     setConflict(false)
     try {
-      await onSave(changes, transcript.revision)
+      await onSave(changes, visible.revision)
       setEditing(false)
       onDirtyChange(false)
     } catch (cause) {
       setConflict(cause instanceof ApiError && cause.status === 409)
       setError(cause instanceof Error ? cause.message : 'Не удалось сохранить исправления')
     } finally { setSaving(false) }
   }
 
   async function reload() {
     if (dirty && !window.confirm('Загрузить актуальную транскрипцию? Ваши несохранённые исправления будут потеряны.')) return
@@ -82,23 +92,22 @@
       const current = await onReload()
       setLoadedTranscript(current)
       setDraft(segmentDraft(current))
       setEditing(false)
       setConflict(false)
       setError('')
       onDirtyChange(false)
     } catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось загрузить транскрипцию') }
   }
 
-  const visible = loadedTranscript.revision === transcript.revision ? transcript : loadedTranscript
   return <div className="transcript-panel">
     <div className="panel-heading"><div className="heading-icon"><AudioLines size={20} /></div><div><p className="eyebrow">РАЗГОВОР</p><h2>Транскрипция</h2></div><span className="version-chip">Версия {visible.revision}</span></div>
     <div className="transcript-meta"><span><Clock3 size={14} /> {formatTime(visible.duration_seconds)}</span><span>{visible.language?.toUpperCase() || 'RU'}</span><span>{visible.stt_model}</span></div>
     <div className="view-tabs" role="tablist" aria-label="Вид транскрипции"><button role="tab" aria-selected={view === 'segments'} onClick={() => setView('segments')}>Разговор</button><button role="tab" aria-selected={view === 'normalized'} onClick={() => setView('normalized')}>Текст</button><button role="tab" aria-selected={view === 'masked'} onClick={() => setView('masked')}>Обезличено</button></div>
     {selection && <div className="selected-source" role="status"><span>Фрагмент записи · {formatTime(selection.start)}</span><q>{selection.quote}</q>{(!visible.audio_available || audioError) && <span>Аудиозапись недоступна</span>}</div>}
     {audioUrl && selection && visible.audio_available && <audio ref={audioRef} src={audioUrl} controls aria-label="Аудиозапись консультации" onLoadedMetadata={event => { event.currentTarget.currentTime = selection.start }} />}
-    <div className="transcript-scroll">{view === 'segments' ? (visible.segments.length ? visible.segments.map((segment, index) => <div className={`segment ${selection?.segmentId === segment.id ? 'selected' : ''}`} key={segment.id}><span className="segment-time">{formatTime(segment.start)}</span><div><span className="segment-speaker">{segment.speaker || 'Участник разговора'}</span>{editing ? <textarea aria-label={`Фрагмент ${index + 1}`} value={draft[segment.id] ?? segment.text} maxLength={20000} rows={3} className="input resize-y" onChange={event => setDraft(current => ({ ...current, [segment.id]: event.target.value }))} /> : <p>{segment.text}</p>}</div></div>) : <p className="transcript-prose">{visible.current_text || 'Текст не распознан.'}</p>) : <p className="transcript-prose whitespace-pre-wrap">{view === 'normalized' ? visible.normalized_text : visible.masked_text}</p>}</div>
+    <div className="transcript-scroll">{view === 'segments' ? (visible.segments.length ? visible.segments.map((segment, index) => <div className={`segment ${selection?.segmentId === segment.id ? 'selected' : ''}`} key={segment.id}><span className="segment-time">{formatTime(segment.start)}</span><div><span className="segment-speaker">{segment.speaker || 'Участник разговора'}</span>{editing ? <textarea aria-label={`Фрагмент ${index + 1}`} value={draft[segment.id] ?? segment.text} maxLength={20000} rows={3} className="input resize-y" readOnly={!editable} onChange={event => setDraft(current => ({ ...current, [segment.id]: event.target.value }))} /> : <p>{segment.text}</p>}</div></div>) : <p className="transcript-prose">{visible.current_text || 'Текст не распознан.'}</p>) : <p className="transcript-prose whitespace-pre-wrap">{view === 'normalized' ? visible.normalized_text : visible.masked_text}</p>}</div>
     {view === 'masked' && <div className="privacy-footer">Маскирование выполняется по правилам и может пропустить персональные данные.</div>}
-    {editable && <div className="transcript-actions">{editing ? <><Button type="button" onClick={() => void save()} disabled={!changes.length || saving || !Object.values(draft).some(value => value.trim())}><Save size={16} /> {saving ? 'Сохраняем…' : 'Сохранить исправления'}</Button><Button type="button" variant="secondary" onClick={() => { setDraft(segmentDraft(visible)); setEditing(false); setError(''); setConflict(false) }} disabled={saving}>Отмена</Button></> : <Button type="button" variant="secondary" onClick={() => { setEditing(true); setView('segments') }}>Исправить текст</Button>}</div>}
+    {editable && <div className="transcript-actions">{editing ? <><Button type="button" onClick={() => void save()} disabled={!changes.length || saving || conflict || !Object.values(draft).some(value => value.trim())}><Save size={16} /> {saving ? 'Сохраняем…' : 'Сохранить исправления'}</Button><Button type="button" variant="secondary" onClick={() => { setDraft(segmentDraft(visible)); setEditing(false); setError(''); setConflict(false) }} disabled={saving}>Отмена</Button></> : <Button type="button" variant="secondary" onClick={() => { setEditing(true); setView('segments') }}>Исправить текст</Button>}</div>}
     {error && <p role="alert" className="action-error">{error}{conflict && <> Версия транскрипции изменилась. Ваши исправления сохранены в форме. <button type="button" onClick={() => void reload()}>Загрузить актуальную версию</button></>}</p>}
   </div>
 }

```

## src/TranscriptPanel.test.tsx
```diff
--- /tmp/medhub-p0-snapshots.BPZlzl/task-7-fix-base/src/TranscriptPanel.test.tsx	2026-09-30 14:54:04.316245949 +0500
+++ src/TranscriptPanel.test.tsx	2026-09-30 14:56:13.077150527 +0500
@@ -22,25 +22,45 @@
   it('retains unsaved text and offers conflict resolution after 409', async () => {
     render(<TranscriptPanel {...props} onSave={vi.fn(async () => { throw new ApiError('Версия устарела', 409) })} />)
     fireEvent.click(screen.getByRole('button', { name: /Исправить текст/ }))
     fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Моя правка' } })
     fireEvent.click(screen.getByRole('button', { name: /Сохранить исправления/ }))
     await screen.findByText(/Версия транскрипции изменилась/)
     expect(screen.getByRole('textbox', { name: /Фрагмент 1/ })).toHaveValue('Моя правка')
     expect(screen.getByRole('button', { name: /Загрузить актуальную версию/ })).toBeVisible()
   })
 
+  it('preserves a dirty draft when a newer transcript revision arrives', async () => {
+    const updated = { ...transcript, revision: 2, segments: [{ ...transcript.segments[0], text: 'Другая правка' }] }
+    const view = render(<TranscriptPanel {...props} />)
+    fireEvent.click(screen.getByRole('button', { name: /Исправить текст/ }))
+    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Моя правка' } })
+    view.rerender(<TranscriptPanel {...props} transcript={updated} />)
+    expect(screen.getByRole('textbox', { name: /Фрагмент 1/ })).toHaveValue('Моя правка')
+    expect(await screen.findByRole('button', { name: /Загрузить актуальную версию/ })).toBeVisible()
+    expect(screen.getByText('Версия 1')).toBeVisible()
+  })
+
   it.each(['APPROVED', 'SENT_TO_MIS'])('keeps %s transcript read-only', () => {
     render(<TranscriptPanel {...props} editable={false} />)
     expect(screen.queryByRole('button', { name: /Исправить текст/ })).not.toBeInTheDocument()
   })
 
+  it('makes an already-open transcript editor read-only when approval arrives', () => {
+    const view = render(<TranscriptPanel {...props} />)
+    fireEvent.click(screen.getByRole('button', { name: /Исправить текст/ }))
+    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Несохранённая правка' } })
+    view.rerender(<TranscriptPanel {...props} editable={false} />)
+    expect(screen.getByRole('textbox', { name: /Фрагмент 1/ })).toHaveAttribute('readonly')
+    expect(screen.queryByRole('button', { name: /Сохранить исправления/ })).not.toBeInTheDocument()
+  })
+
   it('uses server time for selected audio and revokes its URL on consultation switch', async () => {
     vi.spyOn(api, 'audio').mockResolvedValue(new Blob(['synthetic']))
     const create = vi.fn(() => 'blob:synthetic-1')
     const revoke = vi.fn()
     vi.stubGlobal('URL', class extends NativeURL { static createObjectURL = create; static revokeObjectURL = revoke })
     const selection = { segmentId: 'seg-000001', start: 1.25, quote: 'Исходная речь' }
     const view = render(<TranscriptPanel {...props} selection={selection} />)
     const audio = await screen.findByLabelText('Аудиозапись консультации') as HTMLAudioElement
     fireEvent.loadedMetadata(audio)
     expect(audio.currentTime).toBe(1.25)

```

## src/Workspace.test.tsx
```diff
--- /tmp/medhub-p0-snapshots.BPZlzl/task-7-fix-base/src/Workspace.test.tsx	2026-09-30 14:54:04.316375935 +0500
+++ src/Workspace.test.tsx	2026-09-30 14:56:46.016908468 +0500
@@ -1,11 +1,11 @@
-import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
+import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
 import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
 import App from './App'
 import { ApiError, api, setToken } from './api'
 import { emptyClinicalData } from './clinical'
 import type { Consultation, ConsultationTemplate, Document, Transcript } from './types'
 
 const template: ConsultationTemplate = { id: 'therapist', name: 'Осмотр терапевта', fields: [] }
 const transcript: Transcript = { raw_text: 'Исходная речь', normalized_text: 'Исходная речь', masked_text: 'Исходная речь', current_text: 'Исходная речь', language: 'ru', duration_seconds: 3, stt_model: 'demo', revision: 1, audio_available: false, segments: [{ id: 'seg-000001', start: 0, end: 3, text: 'Исходная речь', speaker: null }], pii_entities: [] }
 const document: Document = { id: 'd-1', consultation_id: 'c-1', ai_generated_data: emptyClinicalData, doctor_approved_data: null, data: emptyClinicalData, llm_provider: 'demo', llm_model: 'demo', updated_at: '2026-09-30T00:00:00Z', version: 1, source_transcript_revision: 1, source_masked_text: 'Исходная речь', evidence: [] }
 function item(id: string, status: Consultation['status']): Consultation { return { id, external_patient_id: id === 'c-1' ? 'SYN-1' : 'SYN-2', template_id: 'therapist', status, created_at: '2026-09-30T00:00:00Z', updated_at: '2026-09-30T00:00:00Z', approved_at: status === 'APPROVED' ? '2026-09-30T00:00:00Z' : null, error_message: null, transcript_revision: status === 'RECORDING' ? null : 1, audio_available: status === 'RECORDING', processing_runs: [] } }
@@ -83,20 +83,56 @@
     render(<App />)
     fireEvent.click(await screen.findByRole('button', { name: /Исправить текст/ }))
     fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Несохранённая правка' } })
     fireEvent.click(screen.getByRole('button', { name: /SYN-2/ }))
     expect(screen.getByRole('textbox', { name: /Фрагмент 1/ })).toHaveValue('Несохранённая правка')
     fireEvent.click(screen.getByRole('button', { name: 'Выйти' }))
     expect(confirm).toHaveBeenCalledTimes(2)
     expect(screen.queryByText('Вход в MedHub')).not.toBeInTheDocument()
   })
 
+  it('does not clear the new consultation draft when an old transcript save completes', async () => {
+    setup()
+    const second = item('c-2', 'AI_GENERATED')
+    vi.mocked(api.consultations).mockResolvedValue([item('c-1', 'AI_GENERATED'), second])
+    vi.mocked(api.consultation).mockImplementation(async id => id === 'c-2' ? second : item('c-1', 'AI_GENERATED'))
+    let finishSave!: (value: Transcript) => void
+    vi.spyOn(api, 'editTranscript').mockImplementation(() => new Promise(resolve => { finishSave = resolve }))
+    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
+    render(<App />)
+    fireEvent.click(await screen.findByRole('button', { name: /Исправить текст/ }))
+    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Правка A' } })
+    fireEvent.click(screen.getByRole('button', { name: /Сохранить исправления/ }))
+    await waitFor(() => expect(api.editTranscript).toHaveBeenCalled())
+    fireEvent.click(screen.getByRole('button', { name: /SYN-2/ }))
+    await screen.findByRole('heading', { name: 'SYN-2' })
+    fireEvent.click(await screen.findByRole('button', { name: /Исправить текст/ }))
+    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Правка B' } })
+    await act(async () => finishSave({ ...transcript, revision: 2, segments: [{ ...transcript.segments[0], text: 'Правка A' }] }))
+    expect(screen.getByRole('textbox', { name: /Фрагмент 1/ })).toHaveValue('Правка B')
+    confirm.mockReturnValue(false)
+    fireEvent.click(screen.getByRole('button', { name: /SYN-1/ }))
+    expect(confirm).toHaveBeenCalledTimes(3)
+    expect(screen.getByRole('heading', { name: 'SYN-2' })).toBeVisible()
+  })
+
+  it('blocks approval while transcript corrections are unsaved', async () => {
+    setup('REVIEWED')
+    const approve = vi.spyOn(api, 'approve')
+    render(<App />)
+    fireEvent.click(await screen.findByRole('button', { name: /Исправить текст/ }))
+    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Несохранённая правка' } })
+    fireEvent.click(screen.getByRole('button', { name: /Подтвердить/ }))
+    expect(approve).not.toHaveBeenCalled()
+    expect(await screen.findByText(/Сначала сохраните или отмените исправления транскрипции/)).toBeVisible()
+  })
+
   it('polls while a transcription promise is pending before PROCESSING appears', async () => {
     setup('RECORDING')
     vi.spyOn(api, 'transcribe').mockImplementation(() => new Promise<Transcript>(() => {}))
     render(<App />)
     fireEvent.click(await screen.findByRole('button', { name: /Транскрибировать аудио/ }))
     await waitFor(() => expect(api.consultation).toHaveBeenCalledTimes(2), { timeout: 3500 })
   })
 
   it('offers authenticated PDF preview only for an approved document', async () => {
     setup('APPROVED')

```

## src/App.tsx
```diff
--- /tmp/medhub-p0-snapshots.BPZlzl/task-7-fix-base/src/App.tsx	2026-09-30 14:54:04.316026262 +0500
+++ src/App.tsx	2026-09-30 14:59:02.383882099 +0500
@@ -1,11 +1,11 @@
-import { useCallback, useEffect, useMemo, useState } from 'react'
+import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
 import * as Dialog from '@radix-ui/react-dialog'
 import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query'
 import { Activity, ArrowRight, AudioLines, Check, ChevronRight, CircleAlert, ClipboardCheck, Download, FileClock, FileText, FlaskConical, History, LogOut, Menu, Plus, Search, ShieldCheck, Sparkles, Stethoscope, UploadCloud, X } from 'lucide-react'
 import { api, ApiError, hasToken, setToken } from './api'
 import { DocumentEditor } from './DocumentEditor'
 import { PdfPreview } from './PdfPreview'
 import { PrivacyPanel } from './PrivacyPanel'
 import { ProcessingPanel } from './ProcessingPanel'
 import { Recorder } from './Recorder'
 import { RuntimeNotice } from './RuntimeNotice'
@@ -65,51 +65,55 @@
   const [open, setOpen] = useState(false)
   const audit = useQuery({ queryKey: ['audit', id], queryFn: () => api.audit(id), enabled: open })
   return <section className="audit-panel"><button className="audit-toggle" onClick={() => setOpen(value => !value)} aria-expanded={open}><span><History size={18} /> История правок</span><span>{open ? 'Скрыть' : 'Показать'} <ChevronRight size={16} className={open ? 'rotate-90' : ''} /></span></button>{open && <div className="audit-content">{audit.isLoading ? <p>Загружаем изменения…</p> : audit.isError ? <p role="alert" className="action-error">Не удалось загрузить историю.</p> : audit.data?.length ? audit.data.map(entry => <div className="audit-row" key={entry.id}><div><strong>{entry.field}</strong><span>{formatDate(entry.created_at)}</span></div><span className={entry.changed ? 'changed-label' : 'unchanged-label'}>{entry.changed ? 'Изменено врачом' : 'Без изменений'}</span>{entry.changed && <div className="audit-values"><div><small>ИИ</small><p>{JSON.stringify(entry.ai_value)}</p></div><ArrowRight size={15} /><div><small>Врач</small><p>{JSON.stringify(entry.doctor_value)}</p></div></div>}</div>) : <p>Правок пока нет.</p>}</div>}</section>
 }
 
 function Workspace({ user, demo, externalAI, onLogout }: { user: User; demo: boolean; externalAI: boolean; onLogout: () => void }) {
   const client = useQueryClient()
   const consultations = useQuery({ queryKey: ['consultations'], queryFn: api.consultations })
   const templates = useQuery({ queryKey: ['templates'], queryFn: api.templates })
   const [selectedId, setSelectedId] = useState<string | null>(() => new URLSearchParams(window.location.search).get('consultation'))
+  const activeView = useRef({ id: selectedId, epoch: 0, alive: true })
   const [menuOpen, setMenuOpen] = useState(false)
   const [dirty, setDirty] = useState(false)
   const [transcriptDirty, setTranscriptDirty] = useState(false)
   const [recordingActive, setRecordingActive] = useState(false)
   const [busy, setBusy] = useState(false)
   const [processingPending, setProcessingPending] = useState(false)
   const [error, setError] = useState('')
   const [exportResult, setExportResult] = useState<ExportResult | null>(null)
   const [regenerationRevision, setRegenerationRevision] = useState(0)
   const [selection, setSelection] = useState<SourceSelection | null>(null)
   const [previewOpen, setPreviewOpen] = useState(false)
   const [latestEdit, setLatestEdit] = useState<{ id: string; revision: number } | null>(null)
   const selectConsultation = useCallback((id: string) => {
+    activeView.current = { id, epoch: activeView.current.epoch + 1, alive: true }
     setSelectedId(id)
     const url = new URL(window.location.href)
     url.searchParams.set('consultation', id)
     window.history.replaceState(null, '', url)
   }, [])
   useEffect(() => {
     if (!consultations.data) return
     if ((!selectedId || !consultations.data.some(item => item.id === selectedId)) && consultations.data.length) selectConsultation(consultations.data[0].id)
     else if (selectedId && consultations.data.length === 0) {
+      activeView.current = { id: null, epoch: activeView.current.epoch + 1, alive: true }
       setSelectedId(null)
       const url = new URL(window.location.href)
       url.searchParams.delete('consultation')
       window.history.replaceState(null, '', url)
     }
   }, [selectedId, consultations.data, selectConsultation])
   const consultation = useQuery({ queryKey: ['consultation', selectedId], queryFn: () => api.consultation(selectedId!), enabled: Boolean(selectedId), refetchInterval: query => processingPending || query.state.data?.status === 'PROCESSING' ? 1500 : false })
   const current = consultation.data && latestEdit?.id === selectedId && (consultation.data.transcript_revision ?? 0) < latestEdit.revision
     ? { ...consultation.data, status: 'TRANSCRIBED' as const, transcript_revision: latestEdit.revision } : consultation.data
+  const activeViewEpoch = activeView.current.epoch
   const status = current?.status
   useEffect(() => { if (status) void client.invalidateQueries({ queryKey: ['consultations'] }) }, [status, client])
   const template = templates.data?.find(item => item.id === current?.template_id)
   const transcript = useQuery({ queryKey: transcriptKey(selectedId ?? '', current?.transcript_revision), queryFn: () => api.transcript(selectedId!), enabled: Boolean(selectedId && (hasTranscript(status) || status === 'FAILED' || (status === 'PROCESSING' && current?.transcript_revision !== null))) })
   const document = useQuery({ queryKey: documentKey(selectedId ?? '', current?.transcript_revision), queryFn: () => api.document(selectedId!), enabled: Boolean(selectedId && hasDocument(status)) })
   const freshDocument = Boolean(document.data && hasDocument(status) && document.data.source_transcript_revision === (current?.transcript_revision ?? null) && (!transcript.data || current?.transcript_revision === null || transcript.data.revision === current?.transcript_revision))
   const visibleDocument = freshDocument ? document.data : null
   useEffect(() => {
     if (!dirty && !transcriptDirty && !recordingActive && !busy) return
     const preventLeave = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
@@ -138,59 +142,67 @@
   async function transcribe() { if (!selectedId) return; await act(async () => { await api.transcribe(selectedId); void client.invalidateQueries({ queryKey: ['transcript', selectedId] }); const updated = await api.consultation(selectedId); await refreshSummary(updated) }, true) }
   async function useDemo() { if (!selectedId) return; await act(async () => { await api.demo(selectedId); void client.invalidateQueries({ queryKey: ['transcript', selectedId] }); const updated = await api.consultation(selectedId); await refreshSummary(updated) }, true) }
   async function generate() { if (!selectedId) return; if (dirty && !window.confirm('Черновик содержит несохранённые изменения. Создать заново и потерять их?')) return; await act(async () => { const next = await api.generate(selectedId); client.setQueryData(documentKey(selectedId, next.source_transcript_revision), next); setRegenerationRevision(value => value + 1); const updated = await api.consultation(selectedId); await refreshSummary(updated); setDirty(false) }, true) }
   async function save(data: ClinicalData, version: number): Promise<Document> { if (!selectedId) throw new Error('Выберите консультацию'); const next = await api.save(selectedId, data, version); client.setQueryData(documentKey(selectedId, next.source_transcript_revision), next); const updated = await api.consultation(selectedId); await refreshSummary(updated); void client.invalidateQueries({ queryKey: ['audit', selectedId] }); return next }
   async function reloadDocument(): Promise<Document> { if (!selectedId) throw new Error('Выберите консультацию'); const next = await api.document(selectedId); client.setQueryData(documentKey(selectedId, next.source_transcript_revision), next); return next }
   async function reloadTranscript(): Promise<Transcript> { if (!selectedId) throw new Error('Выберите консультацию'); const next = await api.transcript(selectedId); const updated = await api.consultation(selectedId); client.setQueryData(transcriptKey(selectedId, next.revision), next); await refreshSummary(updated); return next }
   async function saveTranscript(changes: TranscriptTextChange[], expectedRevision: number): Promise<void> {
     if (!selectedId) throw new Error('Выберите консультацию')
     if ((hasDocument(status) || dirty) && !window.confirm('Исправление транскрипции сделает текущий черновик недействительным. Несохранённые правки документа будут потеряны. Продолжить?')) throw new Error('Исправление отменено')
     const id = selectedId
+    const epoch = activeView.current.epoch
     const updated = await api.editTranscript(id, expectedRevision, changes)
+    if (!activeView.current.alive) return
     setLatestEdit({ id, revision: updated.revision })
     client.setQueryData(['consultation', id], (previous: Consultation | undefined) => previous ? { ...previous, status: 'TRANSCRIBED', transcript_revision: updated.revision, error_message: null } : previous)
     client.setQueryData(transcriptKey(id, updated.revision), updated)
     await client.cancelQueries({ queryKey: ['document', id] })
     client.removeQueries({ queryKey: ['document', id] })
-    setSelection(null)
-    setDirty(false)
-    setTranscriptDirty(false)
-    try { await refreshSummary(await api.consultation(id)) } catch { /* optimistic revision remains until next poll */ }
+    if (activeView.current.id === id && activeView.current.epoch === epoch) {
+      setSelection(null)
+      setDirty(false)
+      setTranscriptDirty(false)
+    }
+    try {
+      const summary = await api.consultation(id)
+      if (activeView.current.alive) await refreshSummary(summary)
+    } catch { /* optimistic revision remains until next poll */ }
   }
-  async function approve(version: number) { if (!selectedId || dirty) return; const updated = await api.approve(selectedId, version); await refreshSummary(updated) }
+  async function approve(version: number) { if (!selectedId) throw new Error('Выберите консультацию'); if (transcriptDirty) throw new Error('Сначала сохраните или отмените исправления транскрипции.'); if (dirty) throw new Error('Сначала сохраните изменения документа.'); const updated = await api.approve(selectedId, version); await refreshSummary(updated) }
   async function exportToMis() { if (!selectedId) return; await act(async () => { const result = await api.sendToMis(selectedId); setExportResult(result); const updated = await api.consultation(selectedId); await refreshSummary(updated) }) }
   async function downloadDocx() { if (!selectedId) return; await act(() => api.downloadDocx(selectedId)) }
   const canAudio = status === 'CREATED' || status === 'RECORDING' || (status === 'FAILED' && !transcript.data)
   const canTranscribe = status === 'RECORDING' || (status === 'FAILED' && !transcript.data)
   const canGenerate = status === 'TRANSCRIBED' || status === 'AI_GENERATED' || (status === 'FAILED' && Boolean(transcript.data))
   function safeLogout() {
     if (recordingActive || busy) { setError('Завершите запись или обработку перед выходом.'); return }
     if ((dirty || transcriptDirty) && !window.confirm('Есть несохранённые изменения. Выйти и потерять их?')) return
+    activeView.current = { id: null, epoch: activeView.current.epoch + 1, alive: false }
     setPreviewOpen(false)
     onLogout()
   }
 
   return <div className="app-shell"><Sidebar consultations={consultations.data ?? []} selectedId={selectedId} onSelect={choose} onCreate={create} templates={templates.data ?? []} templatesLoading={templates.isLoading} templatesError={templates.isError} user={user} onLogout={safeLogout} open={menuOpen} onClose={() => setMenuOpen(false)} /><main className="main"><header className="topbar"><div className="topbar-left"><button className="mobile-menu" aria-label="Открыть меню" onClick={() => setMenuOpen(true)}><Menu size={22} /></button><span className="breadcrumb">Рабочая область</span><ChevronRight size={14} /><strong>Консультации</strong></div><div className="topbar-right"><span className="topbar-security"><ShieldCheck size={15} /> Защищённый доступ</span><span className="topbar-avatar">{user.display_name?.charAt(0).toUpperCase() || 'В'}</span></div></header>
     <div className="main-content"><RuntimeNotice demo={demo} externalAI={externalAI} />
     {consultations.isError && <div role="alert" className="page-error"><CircleAlert size={18} /> Не удалось загрузить консультации. <button onClick={() => void consultations.refetch()}>Повторить</button></div>}
     {consultation.isError && <div role="alert" className="page-error"><CircleAlert size={18} /> Не удалось загрузить выбранную консультацию. <button onClick={() => void consultation.refetch()}>Повторить</button></div>}
     {error && <div role="alert" className="page-error"><CircleAlert size={18} /> {error}<button aria-label="Скрыть ошибку" onClick={() => setError('')}><X size={16} /></button></div>}
     {!selectedId && !consultations.isLoading ? <div className="welcome-empty"><div className="welcome-icon"><FileText size={30} /></div><span className="eyebrow">ВАШЕ РАБОЧЕЕ ПРОСТРАНСТВО</span><h1>Начните с новой консультации</h1><p>Создайте запись пациента, добавьте аудио и получите черновик для проверки.</p><NewConsultationDialog onCreate={create} templates={templates.data ?? []} templatesLoading={templates.isLoading} templatesError={templates.isError} /></div> : !current ? <div className="loading-state">Загружаем консультацию…</div> : <>
       <div className="page-heading"><div><div className="page-heading-kicker"><span>КОНСУЛЬТАЦИЯ</span><span className="kicker-divider" />{formatDate(current.created_at)}</div><div className="page-title-line"><h1>{current.external_patient_id}</h1><StatusBadge status={current.status} /></div><p>{template?.name || 'Бланк консультации'} · Документ #{current.id.slice(0, 8)} · {status === 'SENT_TO_MIS' ? 'Передан в тестовый МИС' : 'Подготовка листа консультации'}</p></div><div className="heading-actions">{current.approved_at && <span className="approved-date"><Check size={15} /> Подтверждено {formatDate(current.approved_at)}</span>}{visibleDocument && (status === 'APPROVED' || status === 'SENT_TO_MIS') && <><Button variant="secondary" size="sm" disabled={busy} onClick={() => setPreviewOpen(true)}>Просмотреть PDF</Button><Button variant="secondary" size="sm" disabled={busy} onClick={downloadDocx}><Download size={15} /> Скачать DOCX</Button></>}</div></div>
       <Stepper status={current.status} />
       {current.status === 'FAILED' && <div className="failure-note"><CircleAlert size={18} /><span>{current.error_message || 'Обработка прервалась. Можно повторить доступный этап.'}</span></div>}
       <div className="workflow-grid"><div className="workflow-left"><section className="workspace-card audio-card"><div className="card-topline"><span>01 / ИСХОДНЫЕ ДАННЫЕ</span><span>{hasTranscript(status) ? 'ГОТОВО' : status === 'PROCESSING' ? 'ОБРАБОТКА' : 'ОЖИДАЕТ'}</span></div><h2>Запись приёма</h2><p className="section-subtitle">Добавьте разговор, чтобы подготовить текст консультации.</p>{canAudio ? <Recorder disabled={busy} onBegin={beginRecording} onRecorded={upload} onActiveChange={setRecordingActive} /> : <div className="audio-complete"><div className="audio-complete-icon">{status === 'PROCESSING' ? <AudioLines size={19} /> : <Check size={19} />}</div><div><strong>{status === 'PROCESSING' ? 'Идёт обработка' : 'Аудио обработано'}</strong><p>{status === 'PROCESSING' ? 'Дождитесь завершения текущего этапа.' : 'Транскрипция готова для дальнейшей работы.'}</p></div></div>}
         {demo && (status === 'CREATED' || status === 'FAILED') && <button className="sample-button" disabled={busy || recordingActive} onClick={useDemo}><FlaskConical size={17} /><span>Использовать синтетический пример</span><ArrowRight size={16} /></button>}
         {canTranscribe && <Button className="mt-4" disabled={busy || recordingActive} onClick={transcribe}><AudioLines size={16} /> {busy ? 'Распознаём…' : 'Транскрибировать аудио'}</Button>}
       </section>
       <section className="workspace-card processing-card"><ProcessingPanel runs={current.processing_runs} /></section>
-      {transcript.data && <section className="workspace-card transcript-card"><TranscriptPanel key={selectedId} consultationId={current.id} transcript={transcript.data} editable={Boolean(status && ['TRANSCRIBED', 'AI_GENERATED', 'REVIEWED', 'FAILED'].includes(status))} selection={selection} onSave={saveTranscript} onReload={reloadTranscript} onDirtyChange={setTranscriptDirty} /></section>}
+      {transcript.data && <section className="workspace-card transcript-card"><TranscriptPanel key={selectedId} consultationId={current.id} transcript={transcript.data} editable={Boolean(status && ['TRANSCRIBED', 'AI_GENERATED', 'REVIEWED', 'FAILED'].includes(status))} selection={selection} onSave={saveTranscript} onReload={reloadTranscript} onDirtyChange={nextDirty => { if (activeView.current.alive && activeView.current.id === current.id && activeView.current.epoch === activeViewEpoch) setTranscriptDirty(nextDirty) }} /></section>}
       {hasTranscript(status) && !transcript.data && <section className="workspace-card loading-card">{transcript.isError ? 'Не удалось загрузить транскрипцию.' : 'Загружаем транскрипцию…'}</section>}
       {transcript.data && <section className="workspace-card privacy-card"><PrivacyPanel transcript={transcript.data} document={visibleDocument ?? null} /></section>}
       </div><div className="workflow-right"><section className="workspace-card document-card"><div className="card-topline"><span>02 / КЛИНИЧЕСКИЙ ДОКУМЕНТ</span><span>{status === 'APPROVED' || status === 'SENT_TO_MIS' ? 'ПОДТВЕРЖДЕНО' : status === 'REVIEWED' ? 'ГОТОВО К ПОДТВЕРЖДЕНИЮ' : status === 'AI_GENERATED' ? 'ЧЕРНОВИК ИИ' : 'ОЖИДАЕТ'}</span></div>{visibleDocument && template ? <DocumentEditor key={`${selectedId}-${template.id}`} document={visibleDocument} template={template} status={current.status} busy={busy} regenerationRevision={regenerationRevision} onSave={save} onApprove={approve} onReload={reloadDocument} onDirtyChange={setDirty} onSourceSelect={setSelection} /> : <div className="document-empty"><div className="document-empty-icon"><Sparkles size={25} /></div><h2>{template?.name || 'Черновик консультации'}</h2><p>На основе транскрипции система подготовит структурированный лист. Вы сможете проверить и исправить каждый раздел.</p>{canGenerate && !visibleDocument && <Button disabled={busy} onClick={generate}><Sparkles size={16} /> {busy ? 'Подготавливаем…' : 'Сформировать черновик'}</Button>}{!canGenerate && !visibleDocument && <span className="document-empty-hint">Сначала добавьте и транскрибируйте аудио</span>}{visibleDocument && !template && <span className="document-empty-hint">Загружаем бланк консультации…</span>}{document.isError && <p role="alert" className="action-error">Не удалось загрузить документ.</p>}</div>}
       </section>{visibleDocument && canGenerate && <Button variant="ghost" className="regenerate" disabled={busy} onClick={generate}><Sparkles size={15} /> Сформировать черновик заново</Button>}{visibleDocument && <AuditPanel id={current.id} />}{current.status === 'APPROVED' && <section className="export-card"><div className="export-card-icon"><UploadCloud size={22} /></div><div><h3>Документ подтверждён</h3><p>Отправка в тестовый МИС создаст имитацию экспорта.</p></div><Button disabled={busy} onClick={exportToMis}><UploadCloud size={16} /> Отправить в mock МИС</Button></section>}{current.status === 'SENT_TO_MIS' && <section className="export-card sent"><div className="export-card-icon"><Check size={22} /></div><div><h3>Передано в mock МИС</h3><p>{exportResult?.document_id ? `Тестовый номер документа: ${exportResult.document_id}` : 'Экспорт завершён. Реальная медицинская система не подключена.'}</p></div></section>}</div></div>
     </>}
     <PdfPreview consultationId={selectedId ?? ''} open={Boolean(previewOpen && selectedId && visibleDocument && (status === 'APPROVED' || status === 'SENT_TO_MIS'))} onClose={() => setPreviewOpen(false)} />
     <footer className="app-footer"><span>MedHub · AI Medical Scribe</span><span>Решение и подтверждение всегда остаётся за врачом</span></footer></div></main></div>
 }
 
 function AuthApp() {

```
