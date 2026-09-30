import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from './api'
import { emptyClinicalData } from './clinical'
import { ProtocolPanel } from './ProtocolPanel'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('shows sourced partial criteria and local draft-presence signals without claiming compliance', async () => {
  vi.spyOn(api, 'searchProtocols').mockResolvedValue({ items: [{ id: 'rk-1', name: 'Бронхит', source_url: 'https://example.kz/rk-1', candidate_only: true }] })
  vi.spyOn(api, 'protocol').mockResolvedValue({ id: 'rk-1', name: 'Бронхит', version: 'КП РК 2023', source_url: 'https://example.kz/rk-1', retrieved_at: '2026-09-30T00:00:00Z', scope: 'partial_diagnostic_sections', checklist: [
    { id: 'c1', label: 'Жалобы', quote: 'Оценить характер жалоб', mapped_fields: ['complaints'], manual_review: true },
    { id: 'c2', label: 'Осмотр', quote: 'Провести осмотр', mapped_fields: ['objective_status'], manual_review: true },
    { id: 'c3', label: 'Иные критерии', quote: 'Дополнительная оценка', mapped_fields: [], manual_review: true },
  ] })
  render(<ProtocolPanel consultationId="c-1" data={{ ...emptyClinicalData, complaints: ['Кашель'] }} />)
  fireEvent.change(screen.getByRole('textbox', { name: /Найти протокол РК/ }), { target: { value: 'бронхит' } })
  fireEvent.click(screen.getByRole('button', { name: /Искать/ }))
  fireEvent.click(await screen.findByRole('button', { name: /Бронхит/ }))
  expect(await screen.findByText('КП РК 2023')).toBeVisible()
  expect(screen.getByRole('link', { name: /Открыть источник/ })).toHaveAttribute('href', 'https://example.kz/rk-1')
  expect(screen.getByText('Оценить характер жалоб')).toBeVisible()
  expect(screen.getByText('Есть данные в черновике')).toBeVisible()
  expect(screen.getByText('Нет данных в черновике')).toBeVisible()
  expect(screen.getAllByText('Проверить вручную')).toHaveLength(3)
  expect(screen.getByText(/только часть диагностических разделов/)).toBeVisible()
  expect(screen.queryByText(/соответствует протоколу/i)).not.toBeInTheDocument()
})

it('does not attach a delayed protocol result to a different consultation', async () => {
  let finish!: (value: { items: { id: string; name: string; source_url: string; candidate_only: true }[] }) => void
  vi.spyOn(api, 'searchProtocols').mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const view = render(<ProtocolPanel consultationId="c-1" data={emptyClinicalData} />)
  fireEvent.change(screen.getByRole('textbox', { name: /Найти протокол РК/ }), { target: { value: 'бронхит' } })
  fireEvent.click(screen.getByRole('button', { name: /Искать/ }))
  view.rerender(<ProtocolPanel consultationId="c-2" data={emptyClinicalData} />)
  await act(async () => finish({ items: [{ id: 'rk-1', name: 'Бронхит', source_url: 'https://example.kz/rk-1', candidate_only: true }] }))
  expect(screen.queryByRole('button', { name: /Бронхит/ })).not.toBeInTheDocument()
})
