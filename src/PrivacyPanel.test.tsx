import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { PrivacyPanel } from './PrivacyPanel'
import { emptyClinicalData } from './clinical'
import type { Document, Transcript } from './types'

const transcript: Transcript = {
  raw_text: 'Исходный текст', normalized_text: 'Текущий текст', masked_text: 'Пациент [PERSON_1]', current_text: 'Текущий текст',
  language: 'ru', duration_seconds: 2, stt_model: 'demo', revision: 2, audio_available: false,
  segments: [{ id: 'seg-000001', start: 0, end: 2, text: 'Текущий текст', speaker: null }],
  pii_entities: [{ type: 'PERSON', placeholder: '[PERSON_1]' }, { type: 'PERSON', placeholder: '[PERSON_2]' }, { type: 'PHONE', placeholder: '[PHONE_1]' }],
}
const document: Document = {
  id: 'd-1', consultation_id: 'c-1', ai_generated_data: emptyClinicalData, doctor_approved_data: null, data: emptyClinicalData,
  llm_provider: 'demo', llm_model: 'demo', updated_at: '2026-09-30T00:00:00Z', version: 1,
  source_transcript_revision: 1, source_masked_text: 'Старая обезличенная версия', evidence: [],
}
afterEach(cleanup)

describe('privacy disclosure', () => {
  it('counts detected entities from the current transcript', () => {
    render(<PrivacyPanel transcript={transcript} document={document} />)
    expect(screen.getByText('PERSON: 2')).toBeVisible()
    expect(screen.getByText('PHONE: 1')).toBeVisible()
    expect(screen.getByText('Пациент [PERSON_1]')).toBeVisible()
  })

  it('zero is not a privacy guarantee', () => {
    render(<PrivacyPanel transcript={{ ...transcript, pii_entities: [] }} document={null} />)
    expect(screen.getByText(/Обнаружено: 0/)).toBeVisible()
    expect(screen.getByText(/Маскирование выполняется по правилам и может пропустить персональные данные/)).toBeVisible()
  })

  it('marks revision two as pending when the last generation used revision one', () => {
    render(<PrivacyPanel transcript={transcript} document={document} />)
    expect(screen.getByText('Будет отправлено при генерации: Версия 2')).toBeVisible()
    expect(screen.getByText('Источник последней генерации: Версия 1')).toBeVisible()
    expect(screen.getByText('Старая обезличенная версия')).toBeVisible()
  })

  it('never reconstructs unknown legacy generation input from current text', () => {
    render(<PrivacyPanel transcript={transcript} document={{ ...document, source_transcript_revision: null, source_masked_text: null }} />)
    expect(screen.getByText(/Источник прошлой генерации неизвестен/)).toBeVisible()
    expect(screen.getByText(/Будет отправлено при генерации/)).toBeVisible()
  })
})
