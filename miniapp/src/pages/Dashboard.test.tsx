import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import type { TodayItem, Medication } from '../api/types'

// --- мокаемое состояние хуков (управляем из тестов) ---
const state = vi.hoisted(() => ({
  today: undefined as TodayItem[] | undefined,
  meds: undefined as Medication[] | undefined,
  settings: { timezone: 'Europe/Moscow' } as { timezone: string } | undefined,
  isLoading: false,
  error: null as unknown,
}))

// Стабильные спаи (vi.hoisted — доступны внутри vi.mock-фабрик)
const spies = vi.hoisted(() => ({
  logIntake: vi.fn(),
  apiPost: vi.fn().mockResolvedValue({}),
}))

vi.mock('../api/hooks', () => ({
  useToday: () => ({ data: state.today, isLoading: state.isLoading, error: state.error }),
  useMedications: () => ({ data: state.meds }),
  useSettings: () => ({ data: state.settings }),
  useHearts: () => ({ data: { hearts: 0 } }),
  useLogIntake: () => ({ mutate: spies.logIntake, isPending: false }),
}))

vi.mock('../api/client', () => ({
  api: { post: spies.apiPost },
  apiErrorMessage: (e: unknown) => String(e),
}))

vi.mock('@telegram-apps/sdk-react', () => ({ postEvent: vi.fn() }))

vi.mock('../wishes', () => ({ randomWish: () => 'Держись 💪' }))

import Dashboard from './Dashboard'

// jsdom не реализует DOMMatrixReadOnly — нужен SlideToConfirm.down().
// @ts-expect-error — минимальный полифилл для теста жеста
globalThis.DOMMatrixReadOnly = class { m41 = 0 }

// фабрики фикстур
function todayItem(over: Partial<TodayItem>): TodayItem {
  return {
    medication_id: 1,
    name: 'Аспирин',
    dosage: '1 таб',
    meal_relation: 'any',
    reminder_time: '09:00',
    status: 'pending',
    is_due: false,
    dependent_id: null,
    dependent_name: null,
    ...over,
  }
}

function med(over: Partial<Medication>): Medication {
  return {
    id: 1,
    name: 'Аспирин',
    dosage: '1 таб',
    meal_relation: 'any',
    times_per_day: 1,
    active: 1,
    paused: 0,
    dependent_id: null,
    dependent_name: null,
    stock_qty: null,
    units_per_dose: 1,
    low_stock_days: 3,
    unit_dose_value: null,
    unit_dose_label: 'мг',
    dose_per_intake: null,
    pack_size: null,
    course_total: null,
    rules: [],
    ...over,
  }
}

function renderDash(props?: { onNavigate?: (p: 'medications') => void }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
  return render(<Dashboard {...props} />, { wrapper })
}

beforeEach(() => {
  localStorage.clear()
  state.today = undefined
  state.meds = undefined
  state.settings = { timezone: 'Europe/Moscow' }
  state.isLoading = false
  state.error = null
  spies.logIntake.mockClear()
  spies.apiPost.mockClear()
})

describe('Dashboard empty-state (Фаза 14)', () => {
  beforeEach(() => {
    state.meds = undefined
  })

  it('нет своих препаратов → экран «Пока нет препаратов» + CTA в Аптечку', () => {
    const onNavigate = vi.fn()
    state.today = []
    state.meds = []
    renderDash({ onNavigate })
    expect(screen.getByText('Пока нет препаратов')).toBeInTheDocument()
    fireEvent.click(screen.getByText(/В Аптечку/))
    expect(onNavigate).toHaveBeenCalledWith('medications')
  })

  it('все препараты на паузе → экран «Все препараты на паузе»', () => {
    state.today = []
    state.meds = [med({ paused: 1 })]
    renderDash()
    expect(screen.getByText('Все препараты на паузе')).toBeInTheDocument()
  })

  it('есть активные препараты, но приёмов нет → «На сегодня нет приёмов»', () => {
    state.today = []
    state.meds = [med({ paused: 0 })]
    renderDash()
    expect(screen.getByText('На сегодня нет приёмов')).toBeInTheDocument()
  })
})

describe('Dashboard loading / error', () => {
  it('isLoading → «Загрузка…»', () => {
    state.isLoading = true
    renderDash()
    expect(screen.getByText('Загрузка…')).toBeInTheDocument()
  })

  it('error → текст ошибки', () => {
    state.error = 'Сбой сети'
    renderDash()
    expect(screen.getByText('Сбой сети')).toBeInTheDocument()
  })
})

describe('Dashboard секции «Сейчас»/«Сегодня»', () => {
  beforeEach(() => {
    state.meds = [med({})]
  })

  it('due-pending → «Сейчас»; остальные → «Сегодня»', () => {
    state.today = [
      todayItem({ medication_id: 1, name: 'Утренний', reminder_time: '09:00', status: 'pending', is_due: true }),
      todayItem({ medication_id: 2, name: 'Вечерний', reminder_time: '21:00', status: 'pending', is_due: false }),
    ]
    renderDash()
    expect(screen.getByText('Сейчас')).toBeInTheDocument()
    expect(screen.getByText('Сегодня')).toBeInTheDocument()
    expect(screen.getByText('Утренний')).toBeInTheDocument()
    expect(screen.getByText('Вечерний')).toBeInTheDocument()
  })

  it('«Принять всё» появляется при ≥2 due-pending', () => {
    state.today = [
      todayItem({ medication_id: 1, name: 'A', reminder_time: '09:00', status: 'pending', is_due: true }),
      todayItem({ medication_id: 2, name: 'B', reminder_time: '10:00', status: 'pending', is_due: true }),
    ]
    renderDash()
    expect(screen.getByText('Принять всё')).toBeInTheDocument()
  })

  it('«Принять всё» скрыт при единственном due-pending', () => {
    state.today = [
      todayItem({ medication_id: 1, name: 'A', reminder_time: '09:00', status: 'pending', is_due: true }),
    ]
    renderDash()
    expect(screen.queryByText('Принять всё')).not.toBeInTheDocument()
  })

  it('TZ-баннер при timezone=UTC, закрывается крестиком', () => {
    state.settings = { timezone: 'UTC' }
    state.today = []
    state.meds = [med({ paused: 0 })]
    renderDash()
    expect(screen.getByText(/часовой пояс не задан/)).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Закрыть'))
    expect(screen.queryByText(/часовой пояс не задан/)).not.toBeInTheDocument()
  })
})

describe('Dashboard статус приёма (taken/skipped)', () => {
  beforeEach(() => {
    state.meds = [med({})]
  })

  it('taken → статичная иконка, без слайдера', () => {
    state.today = [todayItem({ status: 'taken', is_due: false })]
    const { container } = renderDash()
    expect(container.querySelector('.med-status--taken')).toBeInTheDocument()
    expect(screen.queryByText('Сдвинь, чтобы принять')).not.toBeInTheDocument()
  })

  it('skipped → статичная иконка skipped', () => {
    state.today = [todayItem({ status: 'skipped', is_due: false })]
    const { container } = renderDash()
    expect(container.querySelector('.med-status--skipped')).toBeInTheDocument()
  })
})

describe('Dashboard отметка приёма (SlideToConfirm / SkipButton)', () => {
  beforeEach(() => {
    state.meds = [med({})]
    state.today = [todayItem({ medication_id: 7, reminder_time: '09:00', status: 'pending', is_due: true })]
  })

  it('слайд до конца → log(taken)', () => {
    const { container } = renderDash()
    const knob = container.querySelector('.slide-knob')!
    // jsdom clientWidth=0 → maxRef=0 → первый pointermove достигает конца
    fireEvent.pointerDown(knob, { clientX: 0, pointerId: 1 })
    fireEvent.pointerMove(knob, { clientX: 0, pointerId: 1 })
    // onConfirm вызывается в requestAnimationFrame
    return waitFor(() => {
      expect(spies.logIntake).toHaveBeenCalledWith(
        expect.objectContaining({ medication_id: 7, status: 'taken', scheduled_time: '09:00' })
      )
    })
  })

  it('SkipButton: первый тап взводит, второй пропускает', () => {
    renderDash()
    const btn = screen.getByLabelText('Пропустить приём')
    fireEvent.click(btn)
    expect(screen.getByText('Тап — пропустить')).toBeInTheDocument()
    expect(spies.logIntake).not.toHaveBeenCalled()
    fireEvent.click(screen.getByLabelText('Подтвердить пропуск'))
    expect(spies.logIntake).toHaveBeenCalledWith(
      expect.objectContaining({ medication_id: 7, status: 'skipped' })
    )
  })
})

describe('Dashboard «Принять всё» (двойной тап + оптимистика)', () => {
  beforeEach(() => {
    state.meds = [med({})]
    state.today = [
      todayItem({ medication_id: 1, name: 'A', reminder_time: '09:00', status: 'pending', is_due: true }),
      todayItem({ medication_id: 2, name: 'B', reminder_time: '10:00', status: 'pending', is_due: true }),
    ]
  })

  it('первый тап взводит, второй шлёт POST на все due', async () => {
    renderDash()
    fireEvent.click(screen.getByText('Принять всё'))
    expect(screen.getByText('Тап — принять всё')).toBeInTheDocument()
    expect(spies.apiPost).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('Тап — принять всё'))
    await waitFor(() => expect(spies.apiPost).toHaveBeenCalledTimes(2))
    expect(spies.apiPost).toHaveBeenCalledWith('/today/intake', expect.objectContaining({ medication_id: 1, status: 'taken' }))
    expect(spies.apiPost).toHaveBeenCalledWith('/today/intake', expect.objectContaining({ medication_id: 2, status: 'taken' }))
  })
})

describe('Dashboard подсказка-слайдер (hold-hint)', () => {
  beforeEach(() => {
    state.meds = [med({})]
    state.today = [todayItem({ status: 'pending', is_due: true })]
  })

  it('первый запуск → подсказка видна', () => {
    renderDash()
    expect(screen.getByText('Сдвиньте бегунок вправо, чтобы отметить приём')).toBeInTheDocument()
  })

  it('slide_learned=1 → подсказка скрыта', () => {
    localStorage.setItem('slide_learned', '1')
    renderDash()
    expect(screen.queryByText('Сдвиньте бегунок вправо, чтобы отметить приём')).not.toBeInTheDocument()
  })
})

describe('Dashboard секции «Забота»', () => {
  beforeEach(() => {
    state.meds = [med({})]
  })

  it('F7 linked → read-only секция, кнопки disabled', () => {
    state.today = [
      todayItem({ medication_id: 5, name: 'Подопечный-мед', status: 'pending', is_due: true, linked_user_id: 99, linked_user_name: 'petya' }),
    ]
    const { container } = renderDash()
    expect(screen.getByText('@petya')).toBeInTheDocument()
    const takeBtn = container.querySelector('.btn-take') as HTMLButtonElement
    const skipBtn = container.querySelector('.btn-skip') as HTMLButtonElement
    expect(takeBtn).toBeDisabled()
    expect(skipBtn).toBeDisabled()
    // read-only → слайдера нет
    expect(container.querySelector('.slide-knob')).not.toBeInTheDocument()
  })

  it('F8 shared → активная карточка со слайдером', () => {
    state.today = [
      todayItem({ medication_id: 6, name: 'Бабушкин-мед', status: 'pending', is_due: true, dep_share_id: 3, dep_share_name: 'Бабушка' }),
    ]
    const { container } = renderDash()
    expect(screen.getByText('Бабушка')).toBeInTheDocument()
    expect(container.querySelector('.slide-knob')).toBeInTheDocument()
  })

  it('локальный близкий → активная карточка со слайдером', () => {
    state.today = [
      todayItem({ medication_id: 8, name: 'Дедов-мед', status: 'pending', is_due: true, dependent_id: 4, dependent_name: 'Дедушка' }),
    ]
    const { container } = renderDash()
    expect(screen.getByText('Дедушка')).toBeInTheDocument()
    expect(container.querySelector('.slide-knob')).toBeInTheDocument()
  })
})
