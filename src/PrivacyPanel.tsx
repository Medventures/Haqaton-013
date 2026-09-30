import type { Document, Transcript } from './types'

export function PrivacyPanel({ transcript, document }: { transcript: Transcript; document: Document | null }) {
  const counts = transcript.pii_entities.reduce<Record<string, number>>((result, entity) => {
    result[entity.type] = (result[entity.type] ?? 0) + 1
    return result
  }, {})
  const sentRevision = document?.source_transcript_revision ?? null
  const currentWasUsed = sentRevision === transcript.revision

  return <section aria-labelledby="privacy-heading" className="privacy-panel">
    <h2 id="privacy-heading">Маскирование и передача данных</h2>
    <p>Текущая транскрипция: Версия {transcript.revision}</p>
    <p>Обнаружено: {transcript.pii_entities.length}</p>
    {transcript.pii_entities.length > 0 && <ul aria-label="Обнаруженные типы данных">
      {Object.entries(counts).sort(([a], [b]) => a.localeCompare(b)).map(([type, count]) => <li key={type}>{type}: {count}</li>)}
    </ul>}
    <p>Маскирование выполняется по правилам и может пропустить персональные данные. Нулевое число обнаружений не гарантирует их отсутствия.</p>
    <h3>Текущий обезличенный текст</h3>
    <p className="whitespace-pre-wrap">{transcript.masked_text || 'Текст отсутствует'}</p>
    {!currentWasUsed && <p>Будет отправлено при генерации: Версия {transcript.revision}</p>}
    {document && <div>
      {sentRevision === null ? <p>Источник прошлой генерации неизвестен.</p> :
        <p>Источник последней генерации: Версия {sentRevision}</p>}
      {document.source_masked_text === null ? <p>Отправленный при прошлой генерации текст неизвестен.</p> :
        <p className="whitespace-pre-wrap">{document.source_masked_text}</p>}
    </div>}
    <p>Аудиозапись остаётся локальной. Перед генерацией исправленный текст маскируется заново.</p>
  </section>
}
