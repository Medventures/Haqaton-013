import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { emptyClinicalData } from './clinical'
import { SourceEvidence } from './SourceEvidence'
import type { ClinicalData, EvidenceLink } from './types'

const source = (path: string): EvidenceLink => ({ field_path: path, segment_id: 'seg-000001', quote: 'Кашель три дня', transcript_revision: 1, start: 12, end: 14 })
const ai: ClinicalData = { ...emptyClinicalData, complaints: ['Кашель', 'Одышка'], medications: [{ name: 'Препарат А', dosage: '10 мг', frequency: null, duration: null }, { name: 'Препарат Б', dosage: '20 мг', frequency: null, duration: null }], diagnosis: 'Острый бронхит', template_fields: [{ key: 'rhythm', value: 'Ритмичный' }, { key: 'tone', value: 'Ясный' }] }
afterEach(cleanup)

describe('AI source links', () => {
  it('shows original value and quote when a scalar changes', () => {
    const onSelect = vi.fn()
    render(<SourceEvidence fieldPath="diagnosis" aiData={ai} currentData={{ ...ai, diagnosis: 'Другой диагноз' }} evidence={[source('diagnosis')]} onSelect={onSelect} />)
    expect(screen.getByText(/Источник AI-версии/)).toBeVisible()
    expect(screen.getByText(/Исходное значение AI: Острый бронхит/)).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: /Кашель три дня/ }))
    expect(onSelect).toHaveBeenCalledWith({ segmentId: 'seg-000001', start: 12, quote: 'Кашель три дня' })
  })

  it.each([
    ['medications/0/name', { ...ai, medications: [ai.medications[1], ai.medications[0]] }],
    ['medications/0/dosage', { ...ai, medications: [ai.medications[1]] }],
    ['medications/0/name', { ...ai, medications: [ai.medications[0], ai.medications[0]] }],
    ['complaints/0', { ...ai, complaints: ['Новый пункт', ...ai.complaints] }],
    ['complaints/0', { ...ai, complaints: ['Кашель', 'Кашель'] }],
  ] as [string, ClinicalData][])('detaches %s when its containing array changes', (fieldPath, currentData) => {
    render(<SourceEvidence fieldPath={fieldPath} aiData={ai} currentData={currentData} evidence={[source(fieldPath)]} onSelect={vi.fn()} />)
    expect(screen.getByText(/Источник AI-версии/)).toBeVisible()
    expect(screen.queryByText(/Источник текущего поля/)).not.toBeInTheDocument()
  })

  it('keeps specialty citations with their stable key after display reorder', () => {
    render(<SourceEvidence fieldPath="template_fields/rhythm" aiData={ai} currentData={{ ...ai, template_fields: [...ai.template_fields].reverse() }} evidence={[source('template_fields/rhythm')]} onSelect={vi.fn()} />)
    expect(screen.getByText(/Источник текущего поля/)).toBeVisible()
    expect(screen.queryByText(/Поле изменено/)).not.toBeInTheDocument()
  })

  it('labels absent evidence as unavailable', () => {
    render(<SourceEvidence fieldPath="diagnosis" aiData={ai} currentData={ai} evidence={[]} onSelect={vi.fn()} />)
    expect(screen.getByText(/Источник не записан/)).toBeVisible()
  })
})
