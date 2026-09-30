import { useEffect, useState } from 'react'
import type { ProcessingErrorCode, ProcessingRun, ProcessingStage } from './types'

const operationNames: Record<ProcessingRun['operation'], string> = {
  upload: 'Загрузка аудио', transcribe: 'Транскрипция', generate: 'Подготовка черновика',
}
const stageNames: Record<string, string> = {
  upload: 'Загрузка файла', stt: 'Распознавание речи', normalization: 'Нормализация текста',
  pii_masking: 'Маскирование персональных данных', llm_extraction: 'Извлечение данных',
  output_validation: 'Проверка результата',
}
const failureNames: Record<ProcessingErrorCode, string> = {
  UPLOAD_FAILED: 'Ошибка загрузки', STT_FAILED: 'Ошибка распознавания',
  NORMALIZATION_FAILED: 'Ошибка нормализации', MASKING_FAILED: 'Ошибка маскирования',
  LLM_FAILED: 'Ошибка извлечения данных', VALIDATION_FAILED: 'Ошибка проверки результата',
  INTERRUPTED: 'Обработка прервана',
}

function seconds(milliseconds: number): string {
  return `${(milliseconds / 1000).toFixed(1).replace('.', ',')} с`
}

function duration(stage: ProcessingStage, now: number, running: boolean): string | null {
  if (stage.status === 'pending') return null
  if (stage.status === 'running' && running && stage.started_at) {
    const started = Date.parse(stage.started_at)
    return Number.isFinite(started) ? seconds(Math.max(0, now - started)) : null
  }
  return stage.duration_ms === null ? null : seconds(stage.duration_ms)
}

function statusText(stage: ProcessingStage): string {
  if (stage.status === 'pending') return 'Ожидает'
  if (stage.status === 'running') return 'Выполняется'
  if (stage.status === 'done') return 'Завершено'
  return stage.error_code ? failureNames[stage.error_code] ?? 'Этап завершился с ошибкой' : 'Этап завершился с ошибкой'
}

export function ProcessingPanel({ runs }: { runs: ProcessingRun[] }) {
  const [now, setNow] = useState(() => Date.now())
  const hasRunningStage = runs.some(run => run.status === 'running' && run.stages.some(stage => stage.status === 'running' && stage.started_at))
  useEffect(() => {
    if (!hasRunningStage) return
    setNow(Date.now())
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [hasRunningStage])

  return <section aria-labelledby="processing-heading" className="processing-panel">
    <h2 id="processing-heading">Ход обработки</h2>
    {runs.length === 0 ? <p>История обработки недоступна. Длительность неизвестна.</p> :
      runs.map(run => <div key={run.id} className="processing-run">
        <h3>{operationNames[run.operation]} — {run.status === 'running' ? 'Выполняется' : run.status === 'done' ? 'Завершено' : 'Ошибка'}</h3>
        {run.stages.length === 0 ? <p>Сведения об этапах отсутствуют. Длительность неизвестна.</p> :
          <ol className="processing-stages">{run.stages.map((stage, index) => {
            const elapsed = duration(stage, now, run.status === 'running')
            return <li key={`${stage.key}-${stage.attempt}-${index}`}>
              <span>{stageNames[stage.key] ?? stage.key}{stage.attempt > 1 ? ` · попытка ${stage.attempt}` : ''}</span>
              <span>{statusText(stage)}</span>
              {elapsed && <span aria-label={`Длительность: ${elapsed}`}>{elapsed}</span>}
              {stage.status !== 'pending' && !elapsed && <span>Длительность неизвестна</span>}
            </li>
          })}</ol>}
      </div>)}
  </section>
}
