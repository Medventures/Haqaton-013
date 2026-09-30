import type { ClinicalData, EvidenceLink } from './types'

export type SourceSelection = { segmentId: string; start: number; quote: string }

type Props = { fieldPath: string; aiData: ClinicalData; currentData: ClinicalData; evidence: EvidenceLink[]; onSelect: (selection: SourceSelection) => void }

function valueAt(data: ClinicalData, path: string): unknown {
  const [root, part, leaf] = path.split('/')
  if (root === 'template_fields') return data.template_fields.find(field => field.key === part)?.value
  const value = data[root as keyof ClinicalData]
  if (part === undefined) return value
  if (!Array.isArray(value)) return value && typeof value === 'object' ? (value as unknown as Record<string, unknown>)[part] : undefined
  const item = value[Number(part)]
  return leaf && item && typeof item === 'object' ? (item as unknown as Record<string, unknown>)[leaf] : item
}

function arrayChanged(aiData: ClinicalData, currentData: ClinicalData, path: string): boolean {
  const root = path.split('/')[0] as keyof ClinicalData
  if (root === 'template_fields') return false
  const original = aiData[root]
  const current = currentData[root]
  return Array.isArray(original) && JSON.stringify(original) !== JSON.stringify(current)
}

function showValue(value: unknown): string {
  if (value == null || value === '') return 'Не указано'
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

export function SourceEvidence({ fieldPath, aiData, currentData, evidence, onSelect }: Props) {
  const aiValue = valueAt(aiData, fieldPath)
  const changed = arrayChanged(aiData, currentData, fieldPath) || JSON.stringify(aiValue) !== JSON.stringify(valueAt(currentData, fieldPath))
  const links = evidence.filter(link => link.field_path === fieldPath)

  return <div className="source-evidence" data-field-path={fieldPath}>
    <p>{changed ? 'Источник AI-версии · Поле изменено врачом' : 'Источник текущего поля · AI-версия'}</p>
    {changed && <p>Исходное значение AI: {showValue(aiValue)}</p>}
    {links.length === 0 ? <p>Источник не записан для этой генерации.</p> : links.map((link, index) =>
      <button type="button" className="source-quote" key={`${link.segment_id}-${index}`} onClick={() => onSelect({ segmentId: link.segment_id, start: link.start, quote: link.quote })} aria-label={`Показать фрагмент записи: ${link.quote}`}>
        <span>Фрагмент записи</span><q>{link.quote}</q>
      </button>)}
  </div>
}
