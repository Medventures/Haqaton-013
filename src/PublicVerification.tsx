import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'

export function PublicVerification({ publicId }: { publicId: string }) {
  const record = useQuery({ queryKey: ['public-verification', publicId], queryFn: () => api.verification(publicId), retry: false })
  const [fileResult, setFileResult] = useState('')

  async function compare(file: File | undefined) {
    setFileResult('')
    if (!file || !record.data) return
    if (!file.name.toLowerCase().endsWith('.pdf')) { setFileResult('Выберите файл PDF.'); return }
    try {
      const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
      const hash = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
      setFileResult(hash.toLowerCase() === record.data.sha256.toLowerCase() ? 'Выбранный PDF совпадает с зарегистрированным хешем.' : 'Выбранный PDF не совпадает с зарегистрированным хешем.')
    } catch { setFileResult('Не удалось проверить файл в этом браузере.') }
  }

  return <main className="public-verification"><div className="verification-card"><p className="eyebrow">MEDHUB · ПРОВЕРКА PDF</p><h1>Проверка записи о документе</h1>
    {record.isLoading && <p>Загружаем запись…</p>}
    {record.isError && <p role="alert">Запись не найдена или временно недоступна.</p>}
    {record.data && <><p role="status">Запись PDF действительна.</p><dl><div><dt>Издатель</dt><dd>{record.data.issuer}</dd></div><div><dt>Дата выпуска</dt><dd>{new Date(record.data.issued_at).toLocaleString('ru-RU')}</dd></div><div><dt>Статус</dt><dd>{record.data.status === 'valid' ? 'Действителен' : record.data.status}</dd></div><div><dt>SHA-256</dt><dd className="verification-hash">{record.data.sha256}</dd></div></dl>
      <label className="field-label">Проверить файл PDF<input type="file" accept="application/pdf,.pdf" onChange={event => void compare(event.target.files?.[0])} /></label>{fileResult && <p role="status">{fileResult}</p>}
      <p className="field-hint">Файл проверяется только в вашем браузере и не загружается на сервер. Это сравнение с зарегистрированным хешем, а не электронная цифровая подпись или государственная проверка.</p>
    </>}
  </div></main>
}
