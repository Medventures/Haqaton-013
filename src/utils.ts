import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { Status } from './types'

export function cn(...values: ClassValue[]) { return twMerge(clsx(values)) }
export const statusLabel: Record<Status, string> = {
  CREATED: 'Создана', RECORDING: 'Запись', PROCESSING: 'Обработка', TRANSCRIBED: 'Транскрибирована',
  AI_GENERATED: 'Черновик ИИ', REVIEWED: 'Проверена врачом', APPROVED: 'Подтверждена', SENT_TO_MIS: 'В МИС', FAILED: 'Ошибка',
}
export function formatDate(value: string) {
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}
export function formatTime(seconds: number) {
  const total = Math.floor(seconds)
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}
