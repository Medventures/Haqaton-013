import { act, cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ProcessingPanel } from './ProcessingPanel'
import type { ProcessingRun, ProcessingStage } from './types'

const stage = (key: string, status: ProcessingStage['status'], values: Partial<ProcessingStage> = {}): ProcessingStage => ({
  key, attempt: 1, status, started_at: null, finished_at: null, duration_ms: null, error_code: null, ...values,
})
const run = (stages: ProcessingStage[], values: Partial<ProcessingRun> = {}): ProcessingRun => ({
  id: 'r-1', operation: 'transcribe', status: 'running', started_at: '2026-09-30T00:00:00Z', finished_at: null, stages, ...values,
})
afterEach(() => { cleanup(); vi.useRealTimers() })

describe('processing status', () => {
  it('pending_has_no_fake_duration', () => {
    render(<ProcessingPanel runs={[run([stage('stt', 'pending')])]} />)
    const item = screen.getByText('Распознавание речи').closest('li')!
    expect(within(item).getByText('Ожидает')).toBeVisible()
    expect(within(item).queryByText(/\d+[,.]\d+ с/)).not.toBeInTheDocument()
  })

  it('running_elapsed_updates_then_stops', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-30T00:00:02Z'))
    const initial = run([stage('stt', 'running', { started_at: '2026-09-30T00:00:00Z' })])
    const view = render(<ProcessingPanel runs={[initial]} />)
    expect(screen.getByText('2,0 с')).toBeVisible()
    act(() => vi.advanceTimersByTime(2000))
    expect(screen.getByText('4,0 с')).toBeVisible()
    view.rerender(<ProcessingPanel runs={[run([stage('stt', 'done', { started_at: '2026-09-30T00:00:00Z', finished_at: '2026-09-30T00:00:03Z', duration_ms: 3000 })], { status: 'done', finished_at: '2026-09-30T00:00:03Z' })]} />)
    expect(screen.getByText('3,0 с')).toBeVisible()
    act(() => vi.advanceTimersByTime(5000))
    expect(screen.getByText('3,0 с')).toBeVisible()
    expect(screen.queryByText('9,0 с')).not.toBeInTheDocument()
  })

  it('failed_stage_keeps_completed_timings', () => {
    render(<ProcessingPanel runs={[run([
      stage('stt', 'done', { duration_ms: 4200 }),
      stage('normalization', 'error', { error_code: 'NORMALIZATION_FAILED' }),
      stage('pii_masking', 'pending'),
    ], { status: 'error', finished_at: '2026-09-30T00:00:05Z' })]} />)
    expect(within(screen.getByText('Распознавание речи').closest('li')!).getByText('4,2 с')).toBeVisible()
    expect(within(screen.getByText('Нормализация текста').closest('li')!).getByText(/Ошибка нормализации/)).toBeVisible()
    expect(within(screen.getByText('Маскирование персональных данных').closest('li')!).getByText('Ожидает')).toBeVisible()
  })

  it('legacy_empty_history_is_unknown', () => {
    render(<ProcessingPanel runs={[]} />)
    expect(screen.getByText(/История обработки недоступна/)).toBeVisible()
    expect(screen.getByText(/Длительность неизвестна/)).toBeVisible()
  })
})
