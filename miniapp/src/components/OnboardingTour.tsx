import { useEffect, useState } from 'react'

// Фаза 14: лёгкий spotlight-тур первого запуска. Подсвечивает кнопки нижней
// навигации (.bottom-nav .nav-item) и поясняет назначение вкладок.
// Флаг прохождения — localStorage 'onboarding_done'. Без внешних библиотек.

const KEY = 'onboarding_done'

interface Step {
  navIndex: number // индекс кнопки в .bottom-nav (0..3)
  title: string
  text: string
}

const STEPS: Step[] = [
  { navIndex: 1, title: 'Аптечка', text: 'Начните здесь — добавьте препарат, дозу и расписание. Управление всеми препаратами тут.' },
  { navIndex: 0, title: 'Приёмы', text: 'Главный экран дня: отмечайте принятые приёмы долгим удержанием ✓.' },
  { navIndex: 2, title: 'Прогресс', text: 'Серии без пропусков, соблюдение и пунктуальность — вся статистика терапии.' },
  { navIndex: 3, title: 'Настройки', text: 'Напоминания, тема оформления, забота о близких и часовой пояс.' },
]

// eslint-disable-next-line react-refresh/only-export-components
export function shouldShowOnboarding(): boolean {
  return !localStorage.getItem(KEY)
}

// Сброс флага — обучение покажется снова (напр. после удаления всех данных).
// eslint-disable-next-line react-refresh/only-export-components
export function resetOnboarding(): void {
  localStorage.removeItem(KEY)
}

interface Rect { left: number; top: number; width: number; height: number }

export default function OnboardingTour({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState(0)
  const [rect, setRect] = useState<Rect | null>(null)
  const cur = STEPS[step]

  useEffect(() => {
    const measure = () => {
      const items = document.querySelectorAll('.bottom-nav .nav-item')
      const el = items[cur.navIndex] as HTMLElement | undefined
      if (el) {
        const r = el.getBoundingClientRect()
        setRect({ left: r.left, top: r.top, width: r.width, height: r.height })
      }
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [cur.navIndex])

  const finish = () => {
    localStorage.setItem(KEY, '1')
    onClose()
  }
  const next = () => (step < STEPS.length - 1 ? setStep((s) => s + 1) : finish())

  const pad = 8
  return (
    <div className="tour-overlay" onClick={next}>
      {rect && (
        <div
          className="tour-spot"
          style={{
            left: rect.left - pad,
            top: rect.top - pad,
            width: rect.width + pad * 2,
            height: rect.height + pad * 2,
          }}
        />
      )}
      <div className="tour-card" onClick={(e) => e.stopPropagation()}>
        <div className="tour-step-count">{step + 1} / {STEPS.length}</div>
        <h3 className="tour-title">{cur.title}</h3>
        <p className="tour-text">{cur.text}</p>
        <div className="tour-actions">
          <button type="button" className="tour-skip" onClick={finish}>Пропустить</button>
          <button type="button" className="tour-next" onClick={next}>
            {step < STEPS.length - 1 ? 'Далее' : 'Понятно'}
          </button>
        </div>
      </div>
    </div>
  )
}
