import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Check, Search, X } from 'lucide-react'
import { api } from './api'
import { Button } from './ui'

export function DiagnosisPicker({ value, onChange, disabled }: { value: string; onChange: (code: string) => void; disabled: boolean }) {
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  useEffect(() => { const timeout = window.setTimeout(() => setDebounced(search.trim()), 300); return () => window.clearTimeout(timeout) }, [search])
  const results = useQuery({ queryKey: ['diagnoses', debounced], queryFn: () => api.diagnoses(debounced), enabled: !disabled && debounced.length >= 2, staleTime: 60_000 })
  if (disabled) return <div className="diagnosis-picker"><span className="field-label">Код МКБ-10</span><div className="diagnosis-readonly">{value || 'Не указан'}</div></div>
  return <div className="diagnosis-picker"><div className="diagnosis-label-row"><label htmlFor="diagnosis-search" className="field-label">Код МКБ-10</label>{value && <span className="diagnosis-selected"><Check size={13} /> {value} <Button type="button" variant="ghost" size="icon" aria-label="Очистить код МКБ-10" disabled={disabled} onClick={() => onChange('')}><X size={12} /></Button></span>}</div><div className="diagnosis-search"><Search size={16} /><input id="diagnosis-search" value={search} onChange={event => setSearch(event.target.value)} disabled={disabled} placeholder="Поиск по коду или названию" autoComplete="off" /></div><p className="diagnosis-help">Код выбирает врач. Поиск не меняет текст диагноза.</p>{debounced.length >= 2 && <div className="diagnosis-results" role="listbox" aria-label="Результаты поиска МКБ-10">{results.isLoading ? <p>Ищем в справочнике…</p> : results.isError ? <p role="alert">Не удалось выполнить поиск.</p> : results.data?.items.length ? results.data.items.map(item => <button key={item.code} type="button" role="option" aria-selected={value === item.code} disabled={disabled} onClick={() => { onChange(item.code); setSearch('') }}><strong>{item.code}</strong><span>{item.name_ru}</span></button>) : <p>Совпадений не найдено.</p>}</div>}</div>
}
