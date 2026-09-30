import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api } from './api'
import { TranscriptPanel } from './TranscriptPanel'
import type { Transcript } from './types'

const transcript: Transcript = { raw_text: 'Исходная речь', current_text: 'Исходная речь', normalized_text: 'Исходная речь', masked_text: 'Исходная речь', language: 'ru', duration_seconds: 5, stt_model: 'demo', revision: 1, audio_available: true, segments: [{ id: 'seg-000001', start: 1.25, end: 3, text: 'Исходная речь', speaker: null }], pii_entities: [] }
const props = { consultationId: 'c-1', transcript, editable: true, selection: null, onSave: vi.fn(async () => {}), onDirtyChange: vi.fn() }
const NativeURL = URL
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('transcript correction and playback', () => {
  it('sends text-only changes with the expected revision', async () => {
    const onSave = vi.fn(async () => {})
    render(<TranscriptPanel {...props} onSave={onSave} />)
    fireEvent.click(screen.getByRole('button', { name: /Исправить текст/ }))
    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Исправленная речь' } })
    fireEvent.click(screen.getByRole('button', { name: /Сохранить исправления/ }))
    await waitFor(() => expect(onSave).toHaveBeenCalledWith([{ segment_id: 'seg-000001', text: 'Исправленная речь' }], 1))
  })

  it('retains unsaved text and offers conflict resolution after 409', async () => {
    render(<TranscriptPanel {...props} onSave={vi.fn(async () => { throw new ApiError('Версия устарела', 409) })} />)
    fireEvent.click(screen.getByRole('button', { name: /Исправить текст/ }))
    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Моя правка' } })
    fireEvent.click(screen.getByRole('button', { name: /Сохранить исправления/ }))
    await screen.findByText(/Версия транскрипции изменилась/)
    expect(screen.getByRole('textbox', { name: /Фрагмент 1/ })).toHaveValue('Моя правка')
    expect(screen.getByRole('button', { name: /Загрузить актуальную версию/ })).toBeVisible()
  })

  it('preserves a dirty draft when a newer transcript revision arrives', async () => {
    const updated = { ...transcript, revision: 2, segments: [{ ...transcript.segments[0], text: 'Другая правка' }] }
    const view = render(<TranscriptPanel {...props} />)
    fireEvent.click(screen.getByRole('button', { name: /Исправить текст/ }))
    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Моя правка' } })
    view.rerender(<TranscriptPanel {...props} transcript={updated} />)
    expect(screen.getByRole('textbox', { name: /Фрагмент 1/ })).toHaveValue('Моя правка')
    expect(await screen.findByRole('button', { name: /Загрузить актуальную версию/ })).toBeVisible()
    expect(screen.getByText('Версия 1')).toBeVisible()
  })

  it.each(['APPROVED', 'SENT_TO_MIS'])('keeps %s transcript read-only', () => {
    render(<TranscriptPanel {...props} editable={false} />)
    expect(screen.queryByRole('button', { name: /Исправить текст/ })).not.toBeInTheDocument()
  })

  it('makes an already-open transcript editor read-only when approval arrives', () => {
    const view = render(<TranscriptPanel {...props} />)
    fireEvent.click(screen.getByRole('button', { name: /Исправить текст/ }))
    fireEvent.change(screen.getByRole('textbox', { name: /Фрагмент 1/ }), { target: { value: 'Несохранённая правка' } })
    view.rerender(<TranscriptPanel {...props} editable={false} />)
    expect(screen.getByRole('textbox', { name: /Фрагмент 1/ })).toHaveAttribute('readonly')
    expect(screen.queryByRole('button', { name: /Сохранить исправления/ })).not.toBeInTheDocument()
  })

  it('uses server time for selected audio and revokes its URL on consultation switch', async () => {
    vi.spyOn(api, 'audio').mockResolvedValue(new Blob(['synthetic']))
    const create = vi.fn(() => 'blob:synthetic-1')
    const revoke = vi.fn()
    vi.stubGlobal('URL', class extends NativeURL { static createObjectURL = create; static revokeObjectURL = revoke })
    const selection = { segmentId: 'seg-000001', start: 1.25, quote: 'Исходная речь' }
    const view = render(<TranscriptPanel {...props} selection={selection} />)
    const audio = await screen.findByLabelText('Аудиозапись консультации') as HTMLAudioElement
    fireEvent.loadedMetadata(audio)
    expect(audio.currentTime).toBe(1.25)
    expect(view.container.querySelector('.segment')).toHaveClass('selected')
    view.rerender(<TranscriptPanel {...props} consultationId="c-2" selection={null} />)
    await waitFor(() => expect(revoke).toHaveBeenCalledWith('blob:synthetic-1'))
  })

  it('keeps source quote and time visible without audio', () => {
    render(<TranscriptPanel {...props} transcript={{ ...transcript, audio_available: false }} selection={{ segmentId: 'seg-000001', start: 1.25, quote: 'Кашель три дня' }} />)
    expect(screen.getByText('Кашель три дня')).toBeVisible()
    expect(screen.getByText(/Аудиозапись недоступна/)).toBeVisible()
    expect(screen.getAllByText(/00:01/)[0]).toBeVisible()
  })

  it('discards a late audio fetch after consultation switch', async () => {
    let resolve!: (blob: Blob) => void
    vi.spyOn(api, 'audio').mockImplementation(() => new Promise<Blob>(done => { resolve = done }))
    const create = vi.fn(() => 'blob:late')
    vi.stubGlobal('URL', class extends NativeURL { static createObjectURL = create; static revokeObjectURL = vi.fn() })
    const view = render(<TranscriptPanel {...props} selection={{ segmentId: 'seg-000001', start: 1.25, quote: 'Речь' }} />)
    view.rerender(<TranscriptPanel {...props} consultationId="c-2" selection={null} />)
    await act(async () => resolve(new Blob(['late'])))
    expect(create).not.toHaveBeenCalled()
  })
})
