import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, ArrowRight, AudioLines, Check, ChevronRight, CircleAlert, ClipboardCheck, Download, FileClock, FileText, FlaskConical, History, LogOut, Menu, Plus, Search, ShieldCheck, Sparkles, Stethoscope, UploadCloud, X } from 'lucide-react'
import { api, ApiError, hasToken, setToken } from './api'
import { DocumentEditor } from './DocumentEditor'
import { PdfPreview } from './PdfPreview'
import { PrivacyPanel } from './PrivacyPanel'
import { ProcessingPanel } from './ProcessingPanel'
import { PublicVerification } from './PublicVerification'
import { Recorder } from './Recorder'
import { RuntimeNotice } from './RuntimeNotice'
import { TranscriptPanel } from './TranscriptPanel'
import type { SourceSelection } from './SourceEvidence'
import type { ClinicalData, Consultation, ConsultationTemplate, Document, ExportResult, Status, Transcript, TranscriptTextChange, User } from './types'
import { Button } from './ui'
import { cn, formatDate, statusLabel } from './utils'

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: (count, error) => !(error instanceof ApiError && [401, 403, 404].includes(error.status)) && count < 1, staleTime: 15_000, refetchOnWindowFocus: false } } })
const hasTranscript = (status?: Status) => Boolean(status && ['TRANSCRIBED', 'AI_GENERATED', 'REVIEWED', 'APPROVED', 'SENT_TO_MIS'].includes(status))
const hasDocument = (status?: Status) => Boolean(status && ['AI_GENERATED', 'REVIEWED', 'APPROVED', 'SENT_TO_MIS'].includes(status))
const documentKey = (id: string, revision: number | null | undefined) => ['document', id, revision] as const
const transcriptKey = (id: string, revision: number | null | undefined) => ['transcript', id, revision] as const

function Mark({ small = false }: { small?: boolean }) {
  return <div className={cn('brand-mark', small && 'brand-mark-small')}><Stethoscope size={small ? 18 : 23} strokeWidth={2.2} /></div>
}

function StatusBadge({ status }: { status: Status }) {
  return <span className={cn('status-badge', `status-${status.toLowerCase()}`)}><span className="badge-dot" />{statusLabel[status]}</span>
}

function Login({ onLogin, demo, externalAI, error }: { onLogin: (username: string, password: string) => Promise<void>; demo: boolean; externalAI: boolean; error: string }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [pending, setPending] = useState(false)
  async function submit(event: React.FormEvent) { event.preventDefault(); setPending(true); try { await onLogin(username.trim(), password) } finally { setPending(false) } }
  return <main className="login-page"><div className="login-decor decor-one" /><div className="login-decor decor-two" /><div className="login-layout"><div className="login-intro"><div className="flex items-center gap-3"><Mark /><span className="brand-word">medhub<span>.</span></span></div><div className="login-copy"><span className="hero-kicker"><span /> РАБОЧЕЕ ПРОСТРАНСТВО ВРАЧА</span><h1>Больше внимания<br /><em>пациенту.</em><br />Меньше рутины.</h1><p>Запишите консультацию, проверьте подготовленный черновик и подтвердите документ, когда всё готово.</p><div className="hero-lines"><div><AudioLines size={19} /> Запись и транскрипция</div><div><ShieldCheck size={19} /> Проверка врачом</div><div><ClipboardCheck size={19} /> Подтверждение и экспорт</div></div></div><p className="login-foot">ИИ помогает оформить сказанное. Клиническое решение остаётся за врачом.</p></div><div className="login-card-wrap"><div className="login-card"><div className="login-card-icon"><Stethoscope size={24} /></div><span className="eyebrow">ДОБРО ПОЖАЛОВАТЬ</span><h2>Вход в MedHub</h2><p>Введите данные вашей учётной записи, чтобы продолжить работу.</p><RuntimeNotice demo={demo} externalAI={externalAI} compact /><form onSubmit={submit} className="login-form"><label className="field-label">Логин<input autoComplete="username" value={username} onChange={event => setUsername(event.target.value)} className="input" required /></label><label className="field-label">Пароль<input type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} className="input" required /></label>{error && <p role="alert" className="action-error">{error}</p>}<Button disabled={pending || !username.trim() || !password} type="submit" className="w-full h-12">{pending ? 'Входим…' : 'Войти'} <ArrowRight size={17} /></Button></form>{demo && <button type="button" className="demo-fill" onClick={() => { setUsername('doctor'); setPassword('demo-doctor') }}>Заполнить демо-доступ <ChevronRight size={15} /></button>}</div><p className="login-card-foot">Защищённое рабочее пространство · MedHub</p></div></div></main>
}

function NewConsultationDialog({ onCreate, templates, templatesLoading, templatesError }: { onCreate: (id: string, templateId: string) => Promise<void>; templates: ConsultationTemplate[]; templatesLoading: boolean; templatesError: boolean }) {
  const [open, setOpen] = useState(false)
  const [patientId, setPatientId] = useState('')
  const [templateId, setTemplateId] = useState('therapist')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function submit(event: React.FormEvent) { event.preventDefault(); setError(''); setBusy(true); try { await onCreate(patientId.trim(), templateId); setOpen(false); setPatientId('') } catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось создать консультацию') } finally { setBusy(false) } }
  return <Dialog.Root open={open} onOpenChange={setOpen}><Dialog.Trigger asChild><Button className="new-consultation"><Plus size={17} /> Новая консультация</Button></Dialog.Trigger><Dialog.Portal><Dialog.Overlay className="dialog-overlay" /><Dialog.Content className="dialog-content"><div className="dialog-head"><div className="heading-icon"><FileText size={20} /></div><Dialog.Close asChild><Button variant="ghost" size="icon" aria-label="Закрыть"><X size={18} /></Button></Dialog.Close></div><Dialog.Title className="dialog-title">Новая консультация</Dialog.Title><Dialog.Description className="dialog-desc">Укажите внешний идентификатор пациента из вашей системы. Не вводите ФИО или ИИН.</Dialog.Description><form onSubmit={submit}><label className="field-label mt-6">ID пациента<input autoFocus value={patientId} onChange={event => setPatientId(event.target.value)} placeholder="Например, PATIENT-1024" maxLength={200} required className="input" /></label><label className="field-label mt-4">Бланк консультации<select className="input" value={templateId} onChange={event => setTemplateId(event.target.value)} disabled={templatesLoading || templatesError}>{templates.map(template => <option value={template.id} key={template.id}>{template.name}</option>)}</select></label>{templatesError && <p role="alert" className="action-error mt-3">Не удалось загрузить бланки. Обновите страницу.</p>}{error && <p role="alert" className="action-error mt-3">{error}</p>}<div className="flex gap-2 justify-end mt-7"><Dialog.Close asChild><Button type="button" variant="secondary">Отмена</Button></Dialog.Close><Button disabled={!patientId.trim() || busy || templatesLoading || templatesError || !templates.some(template => template.id === templateId)} type="submit">{busy ? 'Создаём…' : 'Создать'}</Button></div></form></Dialog.Content></Dialog.Portal></Dialog.Root>
}

function Sidebar({ consultations, selectedId, onSelect, onCreate, templates, templatesLoading, templatesError, user, onLogout, open, onClose }: { consultations: Consultation[]; selectedId: string | null; onSelect: (id: string) => void; onCreate: (id: string, templateId: string) => Promise<void>; templates: ConsultationTemplate[]; templatesLoading: boolean; templatesError: boolean; user: User; onLogout: () => void; open: boolean; onClose: () => void }) {
  const [search, setSearch] = useState('')
  const filtered = useMemo(() => consultations.filter(item => item.external_patient_id.toLowerCase().includes(search.toLowerCase()) || item.id.toLowerCase().includes(search.toLowerCase())), [consultations, search])
  return <><div className={cn('sidebar-scrim', open && 'show')} onClick={onClose} /><aside className={cn('sidebar', open && 'show')}><div className="sidebar-brand"><Mark /><span className="brand-word">medhub<span>.</span></span><button className="sidebar-close" onClick={onClose} aria-label="Закрыть меню"><X size={18} /></button></div><div className="sidebar-main"><p className="sidebar-section-label">РАБОЧАЯ ОБЛАСТЬ</p><div className="sidebar-active"><Activity size={17} /> Консультации</div><div className="sidebar-history-head"><span><History size={16} /> История</span><span className="history-count">{consultations.length}</span></div><div className="search-wrap"><Search size={16} /><input aria-label="Поиск консультаций" placeholder="Найти пациента или ID" value={search} onChange={event => setSearch(event.target.value)} /></div><div className="consultation-list">{filtered.length ? filtered.map(item => <button key={item.id} className={cn('consultation-list-item', selectedId === item.id && 'selected')} onClick={() => { onSelect(item.id); onClose() }}><div className="list-item-top"><span>{item.external_patient_id}</span><ChevronRight size={15} /></div><span className="list-item-date">{formatDate(item.updated_at)}</span><StatusBadge status={item.status} /></button>) : <p className="empty-search">{search ? 'Ничего не найдено' : 'Пока нет консультаций'}</p>}</div></div><div className="sidebar-bottom"><NewConsultationDialog onCreate={onCreate} templates={templates} templatesLoading={templatesLoading} templatesError={templatesError} /><div className="profile"><div className="avatar">{user.display_name?.trim().charAt(0).toUpperCase() || 'В'}</div><div className="profile-text"><strong>{user.display_name || user.username}</strong><span>{user.role === 'admin' ? 'Администратор' : 'Врач'}</span></div><Button size="icon" variant="ghost" aria-label="Выйти" title="Выйти" onClick={onLogout}><LogOut size={17} /></Button></div></div></aside></>
}

function Stepper({ status }: { status: Status }) {
  const steps = [
    { label: 'Создана', icon: FileText }, { label: 'Аудио', icon: AudioLines }, { label: 'Текст', icon: FileClock }, { label: 'Черновик', icon: Sparkles }, { label: 'Проверка', icon: ClipboardCheck }, { label: 'Готово', icon: Check },
  ]
  const position: Record<Status, number> = { CREATED: 0, RECORDING: 1, PROCESSING: 1, TRANSCRIBED: 2, AI_GENERATED: 3, REVIEWED: 4, APPROVED: 5, SENT_TO_MIS: 5, FAILED: 1 }
  return <div className="stepper" aria-label="Этапы консультации">{steps.map((step, index) => <div key={step.label} className={cn('step', index < position[status] && 'done', index === position[status] && 'current')}><div className="step-icon"><step.icon size={16} /></div><span>{step.label}</span></div>)}</div>
}

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
  const activeView = useRef({ id: selectedId, epoch: 0, alive: true })
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
  const [retainedTranscript, setRetainedTranscript] = useState<{ id: string; data: Transcript } | null>(null)
  const selectConsultation = useCallback((id: string) => {
    activeView.current = { id, epoch: activeView.current.epoch + 1, alive: true }
    setSelectedId(id)
    const url = new URL(window.location.href)
    url.searchParams.set('consultation', id)
    window.history.replaceState(null, '', url)
  }, [])
  useEffect(() => {
    if (!consultations.data) return
    if ((!selectedId || !consultations.data.some(item => item.id === selectedId)) && consultations.data.length) selectConsultation(consultations.data[0].id)
    else if (selectedId && consultations.data.length === 0) {
      activeView.current = { id: null, epoch: activeView.current.epoch + 1, alive: true }
      setSelectedId(null)
      const url = new URL(window.location.href)
      url.searchParams.delete('consultation')
      window.history.replaceState(null, '', url)
    }
  }, [selectedId, consultations.data, selectConsultation])
  const consultation = useQuery({ queryKey: ['consultation', selectedId], queryFn: () => api.consultation(selectedId!), enabled: Boolean(selectedId), refetchInterval: query => processingPending || query.state.data?.status === 'PROCESSING' ? 1500 : false })
  const current = consultation.data && latestEdit?.id === selectedId && (consultation.data.transcript_revision ?? 0) < latestEdit.revision
    ? { ...consultation.data, status: 'TRANSCRIBED' as const, transcript_revision: latestEdit.revision } : consultation.data
  const activeViewEpoch = activeView.current.epoch
  const status = current?.status
  useEffect(() => { if (status) void client.invalidateQueries({ queryKey: ['consultations'] }) }, [status, client])
  const template = templates.data?.find(item => item.id === current?.template_id)
  const transcript = useQuery({ queryKey: transcriptKey(selectedId ?? '', current?.transcript_revision), queryFn: () => api.transcript(selectedId!), enabled: Boolean(selectedId && (hasTranscript(status) || status === 'FAILED' || (status === 'PROCESSING' && current?.transcript_revision !== null))) })
  useEffect(() => { if (selectedId && transcript.data) setRetainedTranscript({ id: selectedId, data: transcript.data }) }, [selectedId, transcript.data])
  const visibleTranscript = transcript.data ?? (retainedTranscript?.id === selectedId && current?.transcript_revision != null ? retainedTranscript.data : null)
  const document = useQuery({ queryKey: documentKey(selectedId ?? '', current?.transcript_revision), queryFn: () => api.document(selectedId!), enabled: Boolean(selectedId && hasDocument(status)) })
  const freshDocument = Boolean(document.data && hasDocument(status) && document.data.source_transcript_revision === (current?.transcript_revision ?? null) && (!transcript.data || current?.transcript_revision === null || transcript.data.revision === current?.transcript_revision))
  const visibleDocument = freshDocument ? document.data : null
  useEffect(() => {
    if (!dirty && !transcriptDirty && !recordingActive && !busy) return
    const preventLeave = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', preventLeave)
    return () => window.removeEventListener('beforeunload', preventLeave)
  }, [dirty, transcriptDirty, recordingActive, busy])

  const refreshSummary = useCallback(async (summary: Consultation) => {
    client.setQueryData(['consultation', summary.id], summary)
    await client.invalidateQueries({ queryKey: ['consultations'] })
  }, [client])
  function choose(id: string) {
    if (id === selectedId) return
    if (recordingActive) { setError('Завершите запись или загрузку перед сменой консультации.'); return }
    if ((dirty || transcriptDirty) && !window.confirm('Есть несохранённые изменения. Перейти к другой консультации и потерять их?')) return
    setError(''); setDirty(false); setTranscriptDirty(false); setSelection(null); setPreviewOpen(false); setExportResult(null); selectConsultation(id)
  }
  async function create(externalId: string, templateId: string) {
    if (recordingActive || busy) throw new Error('Завершите запись или обработку перед созданием консультации.')
    if ((dirty || transcriptDirty) && !window.confirm('Есть несохранённые изменения. Создать консультацию и потерять их?')) throw new Error('Создание отменено: сохраните текущие изменения.')
    const item = await api.create(externalId, templateId); await refreshSummary(item); setSelection(null); setPreviewOpen(false); selectConsultation(item.id); setDirty(false); setTranscriptDirty(false); setError('')
  }
  async function act(task: () => Promise<void>, poll = false) { setError(''); setBusy(true); if (poll) setProcessingPending(true); try { await task() } catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось выполнить действие') } finally { setBusy(false); if (poll) setProcessingPending(false) } }
  async function beginRecording() { if (!selectedId) return; const updated = await api.beginRecording(selectedId); await refreshSummary(updated) }
  async function upload(file: File) { if (!selectedId) return; const updated = await api.upload(selectedId, file); await refreshSummary(updated) }
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
    const epoch = activeView.current.epoch
    const updated = await api.editTranscript(id, expectedRevision, changes)
    if (!activeView.current.alive) return
    setLatestEdit({ id, revision: updated.revision })
    client.setQueryData(['consultation', id], (previous: Consultation | undefined) => previous ? { ...previous, status: 'TRANSCRIBED', transcript_revision: updated.revision, error_message: null } : previous)
    client.setQueryData(transcriptKey(id, updated.revision), updated)
    await client.cancelQueries({ queryKey: ['document', id] })
    client.removeQueries({ queryKey: ['document', id] })
    if (activeView.current.id === id && activeView.current.epoch === epoch) {
      setSelection(null)
      setDirty(false)
      setTranscriptDirty(false)
    }
    try {
      const summary = await api.consultation(id)
      if (activeView.current.alive) await refreshSummary(summary)
    } catch { /* optimistic revision remains until next poll */ }
  }
  async function approve(version: number) { if (!selectedId) throw new Error('Выберите консультацию'); if (transcriptDirty) throw new Error('Сначала сохраните или отмените исправления транскрипции.'); if (dirty) throw new Error('Сначала сохраните изменения документа.'); const updated = await api.approve(selectedId, version); await refreshSummary(updated) }
  async function exportToMis() { if (!selectedId) return; await act(async () => { const result = await api.sendToMis(selectedId); setExportResult(result); const updated = await api.consultation(selectedId); await refreshSummary(updated) }) }
  async function downloadDocx() { if (!selectedId) return; await act(() => api.downloadDocx(selectedId)) }
  const canAudio = status === 'CREATED' || status === 'RECORDING' || (status === 'FAILED' && !transcript.data)
  const canTranscribe = status === 'RECORDING' || (status === 'FAILED' && !transcript.data)
  const canGenerate = status === 'TRANSCRIBED' || status === 'AI_GENERATED' || (status === 'FAILED' && Boolean(transcript.data))
  function safeLogout() {
    if (recordingActive || busy) { setError('Завершите запись или обработку перед выходом.'); return }
    if ((dirty || transcriptDirty) && !window.confirm('Есть несохранённые изменения. Выйти и потерять их?')) return
    activeView.current = { id: null, epoch: activeView.current.epoch + 1, alive: false }
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
      {visibleTranscript && <section className="workspace-card transcript-card"><TranscriptPanel key={selectedId} consultationId={current.id} transcript={visibleTranscript} editable={Boolean(status && ['TRANSCRIBED', 'AI_GENERATED', 'REVIEWED', 'FAILED'].includes(status))} selection={selection} onSave={saveTranscript} onReload={reloadTranscript} onDirtyChange={nextDirty => { if (activeView.current.alive && activeView.current.id === current.id && activeView.current.epoch === activeViewEpoch) setTranscriptDirty(nextDirty) }} /></section>}
      {hasTranscript(status) && !visibleTranscript && <section className="workspace-card loading-card">{transcript.isError ? 'Не удалось загрузить транскрипцию.' : 'Загружаем транскрипцию…'}</section>}
      {transcript.data && <section className="workspace-card privacy-card"><PrivacyPanel transcript={transcript.data} document={visibleDocument ?? null} /></section>}
      </div><div className="workflow-right"><section className="workspace-card document-card"><div className="card-topline"><span>02 / КЛИНИЧЕСКИЙ ДОКУМЕНТ</span><span>{status === 'APPROVED' || status === 'SENT_TO_MIS' ? 'ПОДТВЕРЖДЕНО' : status === 'REVIEWED' ? 'ГОТОВО К ПОДТВЕРЖДЕНИЮ' : status === 'AI_GENERATED' ? 'ЧЕРНОВИК ИИ' : 'ОЖИДАЕТ'}</span></div>{visibleDocument && template ? <DocumentEditor key={`${selectedId}-${template.id}`} document={visibleDocument} template={template} status={current.status} busy={busy} regenerationRevision={regenerationRevision} onSave={save} onApprove={approve} onReload={reloadDocument} onDirtyChange={setDirty} onSourceSelect={setSelection} /> : <div className="document-empty"><div className="document-empty-icon"><Sparkles size={25} /></div><h2>{template?.name || 'Черновик консультации'}</h2><p>На основе транскрипции система подготовит структурированный лист. Вы сможете проверить и исправить каждый раздел.</p>{canGenerate && !visibleDocument && <Button disabled={busy} onClick={generate}><Sparkles size={16} /> {busy ? 'Подготавливаем…' : 'Сформировать черновик'}</Button>}{!canGenerate && !visibleDocument && <span className="document-empty-hint">Сначала добавьте и транскрибируйте аудио</span>}{visibleDocument && !template && <span className="document-empty-hint">Загружаем бланк консультации…</span>}{document.isError && <p role="alert" className="action-error">Не удалось загрузить документ.</p>}</div>}
      </section>{visibleDocument && canGenerate && <Button variant="ghost" className="regenerate" disabled={busy} onClick={generate}><Sparkles size={15} /> Сформировать черновик заново</Button>}{visibleDocument && <AuditPanel id={current.id} />}{current.status === 'APPROVED' && <section className="export-card"><div className="export-card-icon"><UploadCloud size={22} /></div><div><h3>Документ подтверждён</h3><p>Отправка в тестовый МИС создаст имитацию экспорта.</p></div><Button disabled={busy} onClick={exportToMis}><UploadCloud size={16} /> Отправить в МИС</Button></section>}{current.status === 'SENT_TO_MIS' && <section className="export-card sent"><div className="export-card-icon"><Check size={22} /></div><div><h3>Передано в тестовый МИС</h3><p>{exportResult?.document_id ? `Тестовый номер документа: ${exportResult.document_id}` : 'Экспорт завершён. Реальная медицинская система не подключена.'}</p></div></section>}</div></div>
    </>}
    <PdfPreview consultationId={selectedId ?? ''} open={Boolean(previewOpen && selectedId && visibleDocument && (status === 'APPROVED' || status === 'SENT_TO_MIS'))} onClose={() => setPreviewOpen(false)} />
    <footer className="app-footer"><span>MedHub · AI Medical Scribe</span><span>Решение и подтверждение всегда остаётся за врачом</span></footer></div></main></div>
}

function AuthApp() {
  const [authenticated, setAuthenticated] = useState(hasToken())
  const [loginError, setLoginError] = useState('')
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, retry: false })
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, enabled: authenticated, retry: false })
  useEffect(() => {
    const handleUnauthorized = () => { setAuthenticated(false); queryClient.clear() }
    window.addEventListener('medhub-unauthorized', handleUnauthorized)
    return () => window.removeEventListener('medhub-unauthorized', handleUnauthorized)
  }, [])
  useEffect(() => { if (me.error instanceof ApiError && me.error.status === 401) { setToken(null); setAuthenticated(false); queryClient.clear() } }, [me.error])
  async function login(username: string, password: string) { setLoginError(''); try { const result = await api.login(username, password); setToken(result.access_token); queryClient.setQueryData(['me'], result.user); setAuthenticated(true) } catch (cause) { setLoginError(cause instanceof Error ? cause.message : 'Не удалось войти') } }
  function logout() { setToken(null); setAuthenticated(false); queryClient.clear() }
  if (health.isError) return <div className="startup-error"><Mark /><h1>Сервер недоступен</h1><p>Не удалось получить состояние MedHub. Проверьте подключение к API.</p><Button onClick={() => void health.refetch()}>Повторить</Button></div>
  if (health.isLoading) return <div className="startup-loading"><Mark /><span>Загружаем MedHub…</span></div>
  if (!authenticated) return <Login onLogin={login} demo={health.data?.mode === 'demo'} externalAI={health.data?.llm_provider === 'openai'} error={loginError} />
  if (me.isLoading) return <div className="startup-loading"><Mark /><span>Восстанавливаем сессию…</span></div>
  if (me.isError) return <div className="startup-error"><Mark /><h1>Не удалось восстановить сессию</h1><p>{me.error instanceof Error ? me.error.message : 'Проверьте соединение.'}</p><Button variant="secondary" onClick={logout}>Войти заново</Button></div>
  return <Workspace user={me.data!} demo={health.data?.mode === 'demo'} externalAI={health.data?.llm_provider === 'openai'} onLogout={logout} />
}

export default function App() {
  const publicId = window.location.pathname.match(/^\/verify\/([A-Za-z0-9_-]{1,64})\/?$/)?.[1]
  return <QueryClientProvider client={queryClient}>{publicId ? <PublicVerification publicId={publicId} /> : <AuthApp />}</QueryClientProvider>
}
