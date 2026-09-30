import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DocumentEditor } from './DocumentEditor'
import { emptyClinicalData } from './clinical'
import type { ClinicalData, ConsultationTemplate, Document } from './types'

const template: ConsultationTemplate = { id: 'cardiologist', name: 'Осмотр кардиолога', fields: [
  { key: 'rhythm', label: 'Ритм сердца', prompt: 'Ритм сердца, частота и особенности', section: 'Осмотр' },
  { key: 'diagnosis', label: 'Диагноз', prompt: 'Диагноз', section: 'Заключение', clinical_field: 'diagnosis' },
] }
const document: Document = { id: 'doc-1', consultation_id: 'c-1', ai_generated_data: emptyClinicalData, doctor_approved_data: null, data: emptyClinicalData, llm_provider: 'demo', llm_model: 'demo', updated_at: '2026-09-30T00:00:00Z', version: 1, source_transcript_revision: 1, source_masked_text: null, evidence: [] }
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('doctor document editor', () => {
  it('collapses empty scalar, vital and specialty fields into Add controls without hiding an opened blank input', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const withNegative: Document = { ...document, data: { ...emptyClinicalData, anamnesis_morbi: 'Отрицает симптомы' } }
    render(<QueryClientProvider client={client}><DocumentEditor document={withNegative} template={template} status="AI_GENERATED" busy={false} regenerationRevision={0} onSave={vi.fn()} onApprove={vi.fn()} onReload={vi.fn()} onDirtyChange={vi.fn()} /></QueryClientProvider>)
    expect(screen.getByRole('textbox', { name: /История заболевания/ })).toHaveValue('Отрицает симптомы')
    expect(screen.queryByRole('textbox', { name: /^Диагноз/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Температура' })).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Ритм сердца' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Добавить: Диагноз' }))
    const diagnosis = screen.getByRole('textbox', { name: /^Диагноз/ })
    fireEvent.change(diagnosis, { target: { value: 'Текст' } })
    fireEvent.change(diagnosis, { target: { value: '' } })
    expect(diagnosis).toBeVisible()
  })

  it('keeps AI evidence selectable on an approved read-only document', () => {
    const onSourceSelect = vi.fn()
    const ai = { ...emptyClinicalData, diagnosis: 'Исходный диагноз' }
    const approved: Document = { ...document, ai_generated_data: ai, data: { ...ai, diagnosis: 'Диагноз врача' }, doctor_approved_data: { ...ai, diagnosis: 'Диагноз врача' }, evidence: [{ field_path: 'diagnosis', segment_id: 'seg-000001', quote: 'Кашель три дня', transcript_revision: 1, start: 4, end: 6 }] }
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><DocumentEditor document={approved} template={template} status="APPROVED" busy={false} regenerationRevision={0} onSave={vi.fn()} onApprove={vi.fn()} onReload={vi.fn()} onDirtyChange={vi.fn()} onSourceSelect={onSourceSelect} /></QueryClientProvider>)
    expect(screen.getByRole('form', { name: /документ/i })).toBeVisible()
    expect(screen.getByText(/Источник AI-версии/)).toBeVisible()
    const source = screen.getByRole('button', { name: /Кашель три дня/ })
    expect(source).toBeEnabled()
    fireEvent.click(source)
    expect(onSourceSelect).toHaveBeenCalledWith({ segmentId: 'seg-000001', start: 4, quote: 'Кашель три дня' })
  })

  it('saves specialty fields with medication and vitals, then enables approval of saved version', async () => {
    let saved: ClinicalData | null = null
    const onSave = vi.fn(async (data: ClinicalData, version: number) => { expect(version).toBe(1); saved = data; return { ...document, data, version: 2 } })
    const onApprove = vi.fn(async (_version: number) => undefined)
    const props = { document, template, status: 'AI_GENERATED' as const, busy: false, regenerationRevision: 0, onSave, onApprove, onReload: vi.fn(async () => document), onDirtyChange: vi.fn() }
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ items: [{ code: 'I10', name_ru: 'Эссенциальная гипертензия', name_kz: null }], total: 1 }), { status: 200, headers: { 'Content-Type': 'application/json' } })))
    const view = render(<QueryClientProvider client={client}><DocumentEditor {...props} /></QueryClientProvider>)
    expect(screen.queryAllByRole('textbox', { name: /^Диагноз/ })).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: 'Добавить: Жалобы' }))
    fireEvent.change(screen.getByLabelText('Жалобы, пункт 1'), { target: { value: 'Одышка' } })
    fireEvent.click(screen.getByRole('button', { name: 'Добавить: Принимаемые препараты' }))
    fireEvent.change(screen.getByLabelText('Принимаемые препараты: название 1'), { target: { value: 'Метопролол' } })
    fireEvent.click(screen.getByRole('button', { name: 'Добавить: Температура' }))
    fireEvent.change(screen.getByLabelText('Температура'), { target: { value: '37.2 °C' } })
    fireEvent.click(screen.getByRole('button', { name: 'Добавить: Ритм сердца' }))
    fireEvent.change(screen.getByLabelText('Ритм сердца'), { target: { value: 'Ритмичный' } })
    fireEvent.click(screen.getByRole('button', { name: 'Добавить: Диагноз' }))
    fireEvent.change(screen.getByRole('textbox', { name: /^Диагноз/ }), { target: { value: 'Гипертензия' } })
    fireEvent.change(screen.getByLabelText('Код МКБ-10'), { target: { value: 'I10' } })
    fireEvent.click((await screen.findByText('Эссенциальная гипертензия')).closest('button')!)
    expect(screen.getByRole('button', { name: 'Подтвердить' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить проверку' }))
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    expect(saved).toMatchObject({ complaints: ['Одышка'], diagnosis: 'Гипертензия', diagnosis_code: 'I10', medications: [{ name: 'Метопролол', dosage: null, frequency: null, duration: null }], vital_signs: { temperature: '37.2 °C' }, template_fields: [{ key: 'rhythm', value: 'Ритмичный' }] })
    view.rerender(<QueryClientProvider client={client}><DocumentEditor {...props} document={{ ...document, data: saved!, version: 2 }} status="REVIEWED" /></QueryClientProvider>)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Подтвердить' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить' }))
    await waitFor(() => expect(onApprove).toHaveBeenCalledWith(2))
  })

  it('keeps unsaved edits on a normal refetch but resets after explicit regeneration', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const props = { document, template, status: 'AI_GENERATED' as const, busy: false, regenerationRevision: 0, onSave: vi.fn(), onApprove: vi.fn(), onReload: vi.fn(async () => document), onDirtyChange: vi.fn() }
    const view = render(<QueryClientProvider client={client}><DocumentEditor {...props} /></QueryClientProvider>)
    fireEvent.click(screen.getByRole('button', { name: 'Добавить: Диагноз' }))
    const diagnosis = screen.getByRole('textbox', { name: /^Диагноз/ }) as HTMLTextAreaElement
    fireEvent.change(diagnosis, { target: { value: 'Моя правка' } })
    await screen.findByText('Есть несохранённые изменения. Сохраните их перед подтверждением.')
    const newDraft = { ...document, data: { ...emptyClinicalData, diagnosis: 'Новый черновик' }, version: 2 }
    view.rerender(<QueryClientProvider client={client}><DocumentEditor {...props} document={newDraft} /></QueryClientProvider>)
    expect(diagnosis.value).toBe('Моя правка')
    expect(screen.getByText('Версия 1')).toBeInTheDocument()
    view.rerender(<QueryClientProvider client={client}><DocumentEditor {...props} document={newDraft} regenerationRevision={1} /></QueryClientProvider>)
    await waitFor(() => expect(diagnosis.value).toBe('Новый черновик'))
    expect(screen.getByText('Версия 2')).toBeInTheDocument()
  })
})
