import { useEffect, useRef, useState } from 'react'
import { AudioLines, Clock3, Save } from 'lucide-react'
import { ApiError, api } from './api'
import { Button } from './ui'
import { formatTime } from './utils'
import type { Transcript, TranscriptTextChange } from './types'
import type { SourceSelection } from './SourceEvidence'

type Props = { consultationId: string; transcript: Transcript; editable: boolean; selection: SourceSelection | null; onSave: (changes: TranscriptTextChange[], expectedRevision: number) => Promise<void>; onDirtyChange: (dirty: boolean) => void; onReload?: () => Promise<Transcript> }

function segmentDraft(transcript: Transcript): Record<string, string> {
  return Object.fromEntries(transcript.segments.map(segment => [segment.id, segment.text]))
}

export function TranscriptPanel({ consultationId, transcript, editable, selection, onSave, onDirtyChange, onReload }: Props) {
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
  const loadedConsultationId = useRef(consultationId)
  const dirty = loadedTranscript.segments.some(segment => (draft[segment.id] ?? segment.text) !== segment.text)

  useEffect(() => {
    if (loadedConsultationId.current === consultationId && loadedTranscript.revision === transcript.revision) return
    if (loadedConsultationId.current === consultationId && saving) return
    if (loadedConsultationId.current === consultationId && editing && dirty) {
      setConflict(true)
      setError('Транскрипция обновилась.')
      return
    }
    loadedConsultationId.current = consultationId
    setDraft(segmentDraft(transcript))
    setLoadedTranscript(transcript)
    setEditing(false)
    setError('')
    setConflict(false)
  }, [consultationId, transcript, loadedTranscript.revision, saving, editing, dirty])
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
      setAudioUrl(url)
    }).catch(cause => {
      if (active && !(cause instanceof Error && cause.name === 'AbortError')) setAudioError(true)
    })
    return () => {
      active = false
      controller.abort()
      if (url) URL.revokeObjectURL(url)
      setAudioUrl(null)
    }
  }, [consultationId, Boolean(selection), transcript.audio_available])
  useEffect(() => {
    if (selection && audioRef.current && audioRef.current.readyState >= 1) audioRef.current.currentTime = selection.start
  }, [selection, audioUrl])

  const visible = loadedTranscript.revision === transcript.revision ? transcript : loadedTranscript
  const changes = visible.segments.filter(segment => (draft[segment.id] ?? segment.text) !== segment.text)
    .map(segment => ({ segment_id: segment.id, text: draft[segment.id] }))

  async function save() {
    if (!changes.length) return
    setSaving(true)
    setError('')
    setConflict(false)
    try {
      await onSave(changes, visible.revision)
      setEditing(false)
      onDirtyChange(false)
    } catch (cause) {
      setConflict(cause instanceof ApiError && cause.status === 409)
      setError(cause instanceof Error ? cause.message : 'Не удалось сохранить исправления')
    } finally { setSaving(false) }
  }

  async function reload() {
    if (dirty && !window.confirm('Загрузить актуальную транскрипцию? Ваши несохранённые исправления будут потеряны.')) return
    if (!onReload) { window.location.reload(); return }
    try {
      const current = await onReload()
      setLoadedTranscript(current)
      setDraft(segmentDraft(current))
      setEditing(false)
      setConflict(false)
      setError('')
      onDirtyChange(false)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось загрузить транскрипцию') }
  }

  return <div className="transcript-panel">
    <div className="panel-heading"><div className="heading-icon"><AudioLines size={20} /></div><div><p className="eyebrow">РАЗГОВОР</p><h2>Транскрипция</h2></div><span className="version-chip">Версия {visible.revision}</span></div>
    <div className="transcript-meta"><span><Clock3 size={14} /> {formatTime(visible.duration_seconds)}</span><span>{visible.language?.toUpperCase() || 'RU'}</span><span>{visible.stt_model}</span></div>
    <div className="view-tabs" role="tablist" aria-label="Вид транскрипции"><button role="tab" aria-selected={view === 'segments'} onClick={() => setView('segments')}>Разговор</button><button role="tab" aria-selected={view === 'normalized'} onClick={() => setView('normalized')}>Текст</button><button role="tab" aria-selected={view === 'masked'} onClick={() => setView('masked')}>Обезличено</button></div>
    {selection && <div className="selected-source" role="status"><span>Фрагмент записи · {formatTime(selection.start)}</span><q>{selection.quote}</q>{(!visible.audio_available || audioError) && <span>Аудиозапись недоступна</span>}</div>}
    {audioUrl && selection && visible.audio_available && <audio ref={audioRef} src={audioUrl} controls aria-label="Аудиозапись консультации" onLoadedMetadata={event => { event.currentTarget.currentTime = selection.start }} />}
    <div className="transcript-scroll">{view === 'segments' ? (visible.segments.length ? visible.segments.map((segment, index) => <div className={`segment ${selection?.segmentId === segment.id ? 'selected' : ''}`} key={segment.id}><span className="segment-time">{formatTime(segment.start)}</span><div><span className="segment-speaker">{segment.speaker || 'Участник разговора'}</span>{editing ? <textarea aria-label={`Фрагмент ${index + 1}`} value={draft[segment.id] ?? segment.text} maxLength={20000} rows={3} className="input resize-y" readOnly={!editable} onChange={event => setDraft(current => ({ ...current, [segment.id]: event.target.value }))} /> : <p>{segment.text}</p>}</div></div>) : <p className="transcript-prose">{visible.current_text || 'Текст не распознан.'}</p>) : <p className="transcript-prose whitespace-pre-wrap">{view === 'normalized' ? visible.normalized_text : visible.masked_text}</p>}</div>
    {view === 'masked' && <div className="privacy-footer">Маскирование выполняется по правилам и может пропустить персональные данные.</div>}
    {editable && <div className="transcript-actions">{editing ? <><Button type="button" onClick={() => void save()} disabled={!changes.length || saving || conflict || !Object.values(draft).some(value => value.trim())}><Save size={16} /> {saving ? 'Сохраняем…' : 'Сохранить исправления'}</Button><Button type="button" variant="secondary" onClick={() => { setDraft(segmentDraft(visible)); setEditing(false); setError(''); setConflict(false) }} disabled={saving}>Отмена</Button></> : <Button type="button" variant="secondary" onClick={() => { setEditing(true); setView('segments') }}>Исправить текст</Button>}</div>}
    {error && <p role="alert" className="action-error">{error}{conflict && <> Версия транскрипции изменилась. Ваши исправления сохранены в форме. <button type="button" onClick={() => void reload()}>Загрузить актуальную версию</button></>}</p>}
  </div>
}
