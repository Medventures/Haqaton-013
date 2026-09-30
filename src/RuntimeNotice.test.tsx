import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { RuntimeNotice } from './RuntimeNotice'

afterEach(cleanup)

it('discloses external text processing without naming the provider', () => {
  render(<RuntimeNotice demo externalAI />)
  expect(screen.getByText(/передаётся внешнему сервису/)).toBeInTheDocument()
  expect(screen.queryByText(/OpenAI/i)).not.toBeInTheDocument()
  expect(screen.getByText(/публичный тестовый пароль/)).toBeInTheDocument()
  expect(screen.queryByText(/Внешние сервисы не вызываются/)).not.toBeInTheDocument()
})

it('does not advertise OpenAI when the fixture provider is active', () => {
  render(<RuntimeNotice demo externalAI={false} />)
  expect(screen.getByText(/встроенном примере/)).toBeInTheDocument()
  expect(screen.queryByText(/OpenAI/i)).not.toBeInTheDocument()
})

it('discloses external processing on the login screen too', () => {
  render(<RuntimeNotice demo externalAI compact />)
  expect(screen.getByText(/передаётся внешнему сервису/)).toBeInTheDocument()
})
