import { FlaskConical, Sparkles } from 'lucide-react'

export function RuntimeNotice({ demo, externalAI, compact = false }: { demo: boolean; externalAI: boolean; compact?: boolean }) {
  if (!demo && !externalAI) return null
  const title = externalAI ? 'Внешняя генерация включена' : 'Демонстрационный режим'
  const description = externalAI
    ? 'При генерации текст после автоматического маскирования передаётся внешнему сервису. Маскирование может пропустить персональные данные.'
    : 'Генерация работает только на встроенном примере. Для своей записи потребуется настроить внешний AI-сервис.'
  const content = <span><strong>{title}</strong> · {description}{demo && ' Используется публичный тестовый пароль: только локальная проверка, не рабочая система.'}</span>
  const icon = externalAI ? <Sparkles size={18} /> : <FlaskConical size={18} />
  if (compact) return <div className="demo-login-note">{icon}{content}</div>
  return <div className="demo-banner"><div>{icon}{content}</div><span className="demo-pill">{externalAI ? 'AI' : 'DEMO'}</span></div>
}
