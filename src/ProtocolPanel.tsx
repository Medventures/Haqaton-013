import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { ClinicalData, ClinicalProtocol, ProtocolCandidate } from './types'

function present(data: ClinicalData | null, field: string): boolean {
  if (!data) return false
  if (field === 'complaints') return data.complaints.some(value => value.trim())
  if (field === 'anamnesis_morbi' || field === 'objective_status') return Boolean(data[field]?.trim())
  if (field === 'vital_signs') return Object.values(data.vital_signs ?? {}).some(value => Boolean(value?.trim()))
  if (field.startsWith('vital_signs.')) return Boolean(data.vital_signs?.[field.slice(12) as keyof NonNullable<ClinicalData['vital_signs']>]?.trim())
  return false
}

function safeSource(url: string): string | null {
  try { return new URL(url).protocol === 'https:' ? url : null } catch { return null }
}

export function ProtocolPanel({ consultationId, data }: { consultationId: string; data: ClinicalData | null }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<ProtocolCandidate[]>([])
  const [selected, setSelected] = useState<ClinicalProtocol | null>(null)
  const [searching, setSearching] = useState(false)
  const [searched, setSearched] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const epoch = useRef(0)
  useEffect(() => { epoch.current += 1; setQuery(''); setResults([]); setSelected(null); setError(''); setSearching(false); setSearched(false); setLoading(false) }, [consultationId])

  async function search(event: React.FormEvent) {
    event.preventDefault()
    if (!query.trim()) return
    const request = ++epoch.current
    setSearching(true); setSearched(false); setError(''); setSelected(null); setResults([])
    try { const found = await api.searchProtocols(query.trim()); if (request === epoch.current) { setResults(found.items); setSearched(true) } }
    catch (cause) { if (request === epoch.current) setError(cause instanceof Error ? cause.message : 'Не удалось найти протоколы РК') }
    finally { if (request === epoch.current) setSearching(false) }
  }

  async function select(id: string) {
    const request = ++epoch.current
    setLoading(true); setError(''); setSelected(null)
    try { const protocol = await api.protocol(id); if (request === epoch.current) setSelected(protocol) }
    catch (cause) { if (request === epoch.current) setError(cause instanceof Error ? cause.message : 'Не удалось подтвердить источник и версию протокола') }
    finally { if (request === epoch.current) setLoading(false) }
  }

  const source = selected ? safeSource(selected.source_url) : null
  return <section className="protocol-panel workspace-card" aria-label="Протоколы РК"><h2>Протоколы РК</h2><p>Поиск врачебных версий. Сверка показывает только наличие сведений в текущем черновике, не медицинское соответствие. Выбор действует только в этом открытом просмотре и не сохраняется.</p>
    <form onSubmit={search} className="protocol-search"><label className="field-label">Найти протокол РК<input className="input" value={query} onChange={event => { setQuery(event.target.value); setSearched(false) }} /></label><button type="submit" disabled={searching || !query.trim()}>{searching ? 'Ищем…' : 'Искать'}</button></form>
    {error && <p role="alert" className="action-error">{error}</p>}
    {searched && !searching && !error && !selected && results.length === 0 && <p>Совпадений нет. Проверьте название протокола РК.</p>}
    {!selected && results.length > 0 && <div className="protocol-results">{results.map(item => <button type="button" key={item.id} onClick={() => void select(item.id)}><strong>{item.name}</strong><span>Кандидат · версия и источник проверяются при выборе</span></button>)}</div>}
    {loading && <p>Проверяем источник и версию…</p>}
    {selected && <div className="protocol-details"><h3>{selected.name}</h3><p className="protocol-version">{selected.version}</p>{source ? <a href={source} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Открыть источник</a> : <p role="alert">Адрес источника недоступен.</p>}
      <p className="protocol-warning">Покрыта только часть диагностических разделов. Каждый пункт требует проверки врачом по первоисточнику; отсутствие данных не означает отрицательный результат.</p>
      <ul>{selected.checklist.map(item => <li key={item.id}><h4>{item.label}</h4><blockquote>{item.quote}</blockquote>{item.mapped_fields.length > 0 && <p>{item.mapped_fields.some(field => present(data, field)) ? 'Есть данные в черновике' : 'Нет данных в черновике'}</p>}<strong>Проверить вручную</strong></li>)}</ul>
    </div>}
  </section>
}
