import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { ApiError, api, setToken } from './api'
import { emptyClinicalData } from './clinical'
import type { Consultation, ConsultationTemplate, Document, Transcript } from './types'

const template: ConsultationTemplate = { id: 'therapist', name: 'Осмотр терапевта', fields: [] }
const transcript: Transcript = { raw_text: 'Исходная речь', normalized_text: 'Исходная речь', masked_text: 'Исходная речь', current_text: 'Исходная речь', language: 'ru', duration_seconds: 3, stt_model: 'demo', revision: 1, audio_available: false, segments: [{ id: 'seg-000001', start: 0, end: 3, text: 'Исходная речь', speaker: null }], pii_entities: [] }
const document: Document = { id: 'd-1', consultation_id: 'c-1', ai_generated_data: emptyClinicalData, doctor_approved_data: null, data: emptyClinicalData, llm_provider: 'demo', llm_model: 'demo', updated_at: '2026-09-30T00:00:00Z', version: 1, source_transcript_revision: 1, source_masked_text: 'Исходная речь', evidence: [] }
function item(id: string, status: Consultation['status']): Consultation { return { id, external_patient_id: id === 'c-1' ? 'SYN-1' : 'SYN-2', template_id: 'therapist', status, created_at: '2026-09-30T00:00:00Z', updated_at: '2026-09-30T00:00:00Z', approved_at: status === 'APPROVED' ? '2026-09-30T00:00:00Z' : null, error_message: null, transcript_revision: status === 'RECORDING' ? null : 1, audio_available: status === 'RECORDING', processing_runs: [] } }

function setup(status: Consultation['status'] = 'AI_GENERATED') {
  let current = item('c-1', status)
  vi.spyOn(api, 'health').mockResolvedValue({ status: 'ok', mode: 'demo', stt_model: 'demo', llm_provider: 'demo', llm_model: 'demo', mis_provider: 'mock' })
  vi.spyOn(api, 'me').mockResolvedValue({ id: 'u-1', username: 'doctor', role: 'doctor', display_name: 'Врач' })
  vi.spyOn(api, 'consultations').mockImplementation(async () => [current, item('c-2', 'CREATED')])
  vi.spyOn(api, 'consultation').mockImplementation(async id => id === 'c-1' ? current : item('c-2', 'CREATED'))
  vi.spyOn(api, 'templates').mockResolvedValue([template])
  vi.spyOn(api, 'transcript').mockResolvedValue(transcript)
  vi.spyOn(api, 'document').mockResolvedValue(document)
  vi.spyOn(api, 'audit').mockResolvedValue([])
  return { update: (next: Consultation) => { current = next } }
}

beforeEach(() => { setToken('test-token'); window.history.replaceState(null, '', '/') })
afterEach(() => { window.dispatchEvent(new Event('medhub-unauthorized')); cleanup(); setToken(null); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('workspace trust workflow', () => {
  it('transcript_save_confirms_draft_invalidation_and_clears_cached_editor even after an old fetch returns', async () => {
    const state = setup()
    let resolveDocument!: (value: Document) => void
    vi.mocked(api.document).mockImplementation(() => new Promise<Document>(resolve => { resolveDocument = resolve }))
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.spyOn(api, 'editTranscript').mockImplementation(async () => {
      state.update({ ...item('c-1', 'TRANSCRIBED'), transcript_revision: 2 })
      return { ...transcript, revision: 2, current_text: 'Исправлено', segments: [{ ...transcript.segments[0], text: 'Исправлено' }] }
    })
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: /Исправить текст/ }))
    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Исправлено' } })
    fireEvent.click(screen.getByRole('button', { name: /Сохранить исправления/ }))
    await waitFor(() => expect(api.editTranscript).toHaveBeenCalledWith('c-1', 1, [{ segment_id: 'seg-000001', text: 'Исправлено' }]))
    expect(confirm).toHaveBeenCalled()
    expect(screen.queryByRole('form', { name: /документ/i })).not.toBeInTheDocument()
    resolveDocument(document)
    await waitFor(() => expect(screen.getByText('Версия 2')).toBeVisible())
    expect(screen.queryByRole('form', { name: /документ/i })).not.toBeInTheDocument()
  })

  it('keeps transcript edits after a stale 409 and leaves the document visible', async () => {
    setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.spyOn(api, 'editTranscript').mockRejectedValue(new ApiError('Версия устарела', 409))
    render(<App />)
    await screen.findByRole('form', { name: /документ/i })
    fireEvent.click(screen.getByRole('button', { name: /Исправить текст/ }))
    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Моя правка' } })
    fireEvent.click(screen.getByRole('button', { name: /Сохранить исправления/ }))
    await screen.findByText(/Версия транскрипции изменилась/)
    expect(screen.getByRole('textbox', { name: /Фрагмент 1/ })).toHaveValue('Моя правка')
    expect(screen.getByRole('form', { name: /документ/i })).toBeVisible()
  })

  it('keeps a dirty transcript mounted while a newer revision is fetched and requires explicit resolution', async () => {
    const state = setup()
    let finishTranscript!: (value: Transcript) => void
    vi.mocked(api.transcript).mockImplementationOnce(async () => transcript)
      .mockImplementationOnce(() => new Promise(resolve => { finishTranscript = resolve }))
    vi.spyOn(api, 'generate').mockImplementation(() => new Promise<Document>(() => {}))
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: /Исправить текст/ }))
    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Моя несохранённая правка' } })
    fireEvent.click(screen.getByRole('button', { name: /Сформировать черновик заново/ }))
    state.update({ ...item('c-1', 'AI_GENERATED'), transcript_revision: 2 })
    await waitFor(() => expect(api.transcript).toHaveBeenCalledTimes(2), { timeout: 3500 })
    expect(screen.getByRole('textbox', { name: /Фрагмент 1/ })).toHaveValue('Моя несохранённая правка')
    await act(async () => finishTranscript({ ...transcript, revision: 2, segments: [{ ...transcript.segments[0], text: 'Новая серверная версия' }] }))
    expect(screen.getByRole('textbox', { name: /Фрагмент 1/ })).toHaveValue('Моя несохранённая правка')
    expect(screen.getByRole('button', { name: /Загрузить актуальную версию/ })).toBeVisible()
    expect(screen.getByText('Версия 1')).toBeVisible()
  })

  it('preserves the transcript draft when invalidation confirmation is declined', async () => {
    setup()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const edit = vi.spyOn(api, 'editTranscript')
    render(<App />)
    await screen.findByRole('form', { name: /документ/i })
    fireEvent.click(screen.getByRole('button', { name: /Исправить текст/ }))
    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Моя правка' } })
    fireEvent.click(screen.getByRole('button', { name: /Сохранить исправления/ }))
    await waitFor(() => expect(confirm).toHaveBeenCalledOnce())
    expect(edit).not.toHaveBeenCalled()
    expect(screen.getByRole('textbox', { name: /Фрагмент 1/ })).toHaveValue('Моя правка')
    expect(screen.getByRole('form', { name: /документ/i })).toBeVisible()
  })

  it('guards navigation and logout while transcript text is dirty', async () => {
    setup()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: /Исправить текст/ }))
    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Несохранённая правка' } })
    fireEvent.click(screen.getByRole('button', { name: /SYN-2/ }))
    expect(screen.getByRole('textbox', { name: /Фрагмент 1/ })).toHaveValue('Несохранённая правка')
    fireEvent.click(screen.getByRole('button', { name: 'Выйти' }))
    expect(confirm).toHaveBeenCalledTimes(2)
    expect(screen.queryByText('Вход в MedHub')).not.toBeInTheDocument()
  })

  it('does not clear the new consultation draft when an old transcript save completes', async () => {
    setup()
    const second = item('c-2', 'AI_GENERATED')
    vi.mocked(api.consultations).mockResolvedValue([item('c-1', 'AI_GENERATED'), second])
    vi.mocked(api.consultation).mockImplementation(async id => id === 'c-2' ? second : item('c-1', 'AI_GENERATED'))
    let finishSave!: (value: Transcript) => void
    vi.spyOn(api, 'editTranscript').mockImplementation(() => new Promise(resolve => { finishSave = resolve }))
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: /Исправить текст/ }))
    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Правка A' } })
    fireEvent.click(screen.getByRole('button', { name: /Сохранить исправления/ }))
    await waitFor(() => expect(api.editTranscript).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: /SYN-2/ }))
    await screen.findByRole('heading', { name: 'SYN-2' })
    fireEvent.click(await screen.findByRole('button', { name: /Исправить текст/ }))
    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Правка B' } })
    await act(async () => finishSave({ ...transcript, revision: 2, segments: [{ ...transcript.segments[0], text: 'Правка A' }] }))
    expect(screen.getByRole('textbox', { name: /Фрагмент 1/ })).toHaveValue('Правка B')
    confirm.mockReturnValue(false)
    fireEvent.click(screen.getByRole('button', { name: /SYN-1/ }))
    expect(confirm).toHaveBeenCalledTimes(3)
    expect(screen.getByRole('heading', { name: 'SYN-2' })).toBeVisible()
  })

  it('blocks approval while transcript corrections are unsaved', async () => {
    setup('REVIEWED')
    const approve = vi.spyOn(api, 'approve')
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: /Исправить текст/ }))
    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Несохранённая правка' } })
    fireEvent.click(screen.getByRole('button', { name: /Подтвердить/ }))
    expect(approve).not.toHaveBeenCalled()
    expect(await screen.findByText(/Сначала сохраните или отмените исправления транскрипции/)).toBeVisible()
  })

  it('polls while a transcription promise is pending before PROCESSING appears', async () => {
    setup('RECORDING')
    vi.spyOn(api, 'transcribe').mockImplementation(() => new Promise<Transcript>(() => {}))
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: /Транскрибировать аудио/ }))
    await waitFor(() => expect(api.consultation).toHaveBeenCalledTimes(2), { timeout: 3500 })
  })

  it('offers authenticated PDF preview only for an approved document', async () => {
    setup('APPROVED')
    vi.spyOn(api, 'pdf').mockRejectedValue(new ApiError('Не удалось загрузить PDF', 502))
    render(<App />)
    const open = await screen.findByRole('button', { name: /Просмотреть PDF/ })
    fireEvent.click(open)
    expect(await screen.findByRole('dialog', { name: /Просмотр PDF/ })).toBeVisible()
  })

  it('checks protocol field presence against unsaved clinical edits in memory', async () => {
    setup()
    vi.spyOn(api, 'searchProtocols').mockResolvedValue({ items: [{ id: 'rk-1', name: 'Бронхит', source_url: 'https://example.kz/rk-1', candidate_only: true }] })
    vi.spyOn(api, 'protocol').mockResolvedValue({ id: 'rk-1', name: 'Бронхит', version: 'КП РК 2023', source_url: 'https://example.kz/rk-1', retrieved_at: '2026-09-30T00:00:00Z', scope: 'partial_diagnostic_sections', checklist: [{ id: 'c1', label: 'Жалобы', quote: 'Оценить жалобы', mapped_fields: ['complaints'], manual_review: true }] })
    render(<App />)
    await screen.findByRole('form', { name: /документ/i })
    fireEvent.click(screen.getByRole('button', { name: 'Добавить: Жалобы' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Жалобы, пункт 1' }), { target: { value: 'Синтетический кашель' } })
    fireEvent.change(screen.getByRole('textbox', { name: /Найти протокол РК/ }), { target: { value: 'бронхит' } })
    fireEvent.click(screen.getByRole('button', { name: /Искать/ }))
    fireEvent.click(await screen.findByRole('button', { name: /Бронхит/ }))
    expect(await screen.findByText('Есть данные в черновике')).toBeVisible()
  })
})
