import { useEffect, useRef, useState } from 'react'
import { Mic, Square, Upload, Waves } from 'lucide-react'
import { Button } from './ui'
import { formatTime } from './utils'

const MAX_BYTES = 50 * 1024 * 1024
const accepted = ['audio/webm', 'audio/wav', 'audio/x-wav', 'audio/wave', 'audio/mpeg', 'audio/mp3', 'audio/mp4', 'audio/x-m4a', 'audio/m4a']
const extensions = ['webm', 'wav', 'mp3', 'm4a']

function validateFile(file: File) {
  if (!file.size) throw new Error('Аудиофайл пустой.')
  if (file.size > MAX_BYTES) throw new Error('Файл больше 50 МБ. Выберите запись меньшего размера.')
  const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
  const mime = file.type.split(';')[0].toLowerCase()
  if (!extensions.includes(extension) || (mime && !accepted.includes(mime))) throw new Error('Поддерживаются только WebM, WAV, MP3 и M4A.')
}

function normalizedUpload(file: File): File {
  const type = file.type.split(';')[0].toLowerCase()
  const extension = file.name.split('.').pop()?.toLowerCase()
  const inferred = extension === 'webm' ? 'audio/webm' : extension === 'wav' ? 'audio/wav' : extension === 'mp3' ? 'audio/mpeg' : extension === 'm4a' ? 'audio/mp4' : ''
  const normalized = type === 'audio/wave' ? 'audio/wav' : type === 'audio/mp3' ? 'audio/mpeg' : type === 'audio/m4a' ? 'audio/x-m4a' : type || inferred
  return normalized === type ? file : new File([file], file.name, { type: normalized })
}

type Props = { disabled: boolean; onBegin: () => Promise<void>; onRecorded: (file: File) => Promise<void>; onActiveChange: (active: boolean) => void }
export function Recorder({ disabled, onBegin, onRecorded, onActiveChange }: Props) {
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const bytesRef = useRef(0)
  const recordErrorRef = useRef(false)
  const aliveRef = useRef(true)
  const inputRef = useRef<HTMLInputElement>(null)
  const [state, setState] = useState<'idle' | 'requesting' | 'recording' | 'uploading'>('idle')
  const [seconds, setSeconds] = useState(0)
  const [error, setError] = useState('')
  useEffect(() => {
    aliveRef.current = true
    return () => {
      aliveRef.current = false
      if (recorderRef.current?.state === 'recording') recorderRef.current.stop()
      streamRef.current?.getTracks().forEach(track => track.stop())
      recorderRef.current = null
      streamRef.current = null
    }
  }, [])
  useEffect(() => {
    if (state !== 'recording') return
    const interval = window.setInterval(() => setSeconds(value => value + 1), 1000)
    return () => window.clearInterval(interval)
  }, [state])
  useEffect(() => onActiveChange(state !== 'idle'), [state, onActiveChange])

  async function start() {
    setError('')
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError('Этот браузер не поддерживает запись. Загрузите готовый аудиофайл.'); return
    }
    setState('requesting')
    let stream: MediaStream | null = null
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (!aliveRef.current) { stream.getTracks().forEach(track => track.stop()); return }
      const mimeType = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find(type => MediaRecorder.isTypeSupported(type))
      if (!mimeType) throw new Error('Нет поддерживаемого формата записи. Загрузите готовый файл.')
      const recorder = new MediaRecorder(stream, { mimeType })
      await onBegin()
      if (!aliveRef.current) { stream.getTracks().forEach(track => track.stop()); return }
      chunksRef.current = []
      bytesRef.current = 0
      recordErrorRef.current = false
      streamRef.current = stream
      recorderRef.current = recorder
      recorder.ondataavailable = event => {
        if (!event.data.size || recordErrorRef.current) return
        bytesRef.current += event.data.size
        if (bytesRef.current > MAX_BYTES) {
          recordErrorRef.current = true
          if (aliveRef.current) setError('Запись превысила 50 МБ. Начните новую запись или загрузите файл меньшего размера.')
          if (recorder.state === 'recording') recorder.stop()
          return
        }
        chunksRef.current.push(event.data)
      }
      recorder.onerror = () => {
        recordErrorRef.current = true
        if (aliveRef.current) setError('Ошибка записи. Попробуйте ещё раз или загрузите файл.')
        streamRef.current?.getTracks().forEach(track => track.stop())
        streamRef.current = null
        if (aliveRef.current) setState('idle')
      }
      recorder.onstop = async () => {
        streamRef.current?.getTracks().forEach(track => track.stop())
        streamRef.current = null
        recorderRef.current = null
        if (!aliveRef.current || recordErrorRef.current) { chunksRef.current = []; if (aliveRef.current) setState('idle'); return }
        setState('uploading')
        try {
          const extension = mimeType.startsWith('audio/mp4') ? 'm4a' : 'webm'
          const file = new File(chunksRef.current, `consultation-${Date.now()}.${extension}`, { type: mimeType })
          validateFile(file)
          await onRecorded(file)
        } catch (cause) { if (aliveRef.current) setError(cause instanceof Error ? cause.message : 'Не удалось загрузить запись') }
        finally { chunksRef.current = []; if (aliveRef.current) setState('idle') }
      }
      recorder.start(1000)
      setSeconds(0)
      setState('recording')
    } catch (cause) {
      stream?.getTracks().forEach(track => track.stop())
      if (aliveRef.current) {
        setError(cause instanceof DOMException && cause.name === 'NotAllowedError' ? 'Доступ к микрофону запрещён. Разрешите его в браузере или загрузите файл.' : cause instanceof Error ? cause.message : 'Не удалось начать запись')
        setState('idle')
      }
    }
  }
  function stop() {
    if (recorderRef.current?.state === 'recording') { recorderRef.current.requestData(); recorderRef.current.stop() }
  }
  async function selected(file?: File) {
    if (!file) return
    setError('')
    try { validateFile(file); setState('uploading'); await onRecorded(normalizedUpload(file)) }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось загрузить файл') }
    finally { setState('idle'); if (inputRef.current) inputRef.current.value = '' }
  }

  return <div className="recording-box"><div className="recording-graphic"><div className={`recording-orb ${state === 'recording' ? 'active' : ''}`}><Waves size={29} /></div></div>
    <div className="recording-content"><div className="flex items-center gap-2"><span className={`live-dot ${state === 'recording' ? 'active' : ''}`} /><span className="eyebrow">Аудио консультации</span></div><h3>{state === 'recording' ? `Идёт запись · ${formatTime(seconds)}` : state === 'requesting' ? 'Подключаем микрофон…' : state === 'uploading' ? 'Загружаем аудио…' : 'Запишите разговор или загрузите файл'}</h3><p>После загрузки запустите локальную транскрипцию. Максимум 50 МБ.</p>
      <div className="flex flex-wrap gap-2 mt-5"><Button onClick={state === 'recording' ? stop : start} disabled={disabled || (state !== 'idle' && state !== 'recording')} variant={state === 'recording' ? 'danger' : 'primary'}>{state === 'recording' ? <><Square size={16} fill="currentColor" /> Завершить запись</> : <><Mic size={17} /> Начать запись</>}</Button><Button variant="secondary" onClick={() => inputRef.current?.click()} disabled={disabled || state !== 'idle'}><Upload size={16} /> Загрузить файл</Button><input ref={inputRef} className="sr-only" type="file" accept=".webm,.wav,.mp3,.m4a,audio/webm,audio/wav,audio/mpeg,audio/mp4" onChange={event => void selected(event.target.files?.[0])} /></div>
      {error && <p role="alert" className="action-error mt-3">{error}</p>}</div></div>
}
