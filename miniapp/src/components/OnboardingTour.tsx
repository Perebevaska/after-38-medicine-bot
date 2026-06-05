import { useEffect, useRef, useState } from 'react'

// Онбординг-тур первого запуска. Переключает активную вкладку под каждый шаг,
// подсвечивает пункт нав-бара ИЛИ элемент(ы) внутри страницы (по селектору,
// скоуп — активная .tab-panel). Несколько селекторов → подсветка их объединения.
// Флаг прохождения — localStorage 'onboarding_done'. Без внешних библиотек.

const KEY = 'onboarding_done'
const NAV_ORDER = ['dashboard', 'medications', 'stats', 'settings'] as const
type NavPage = typeof NAV_ORDER[number]

interface Step {
  tab: NavPage
  // 'nav' → иконка пункта нав-бара этой вкладки; строка/массив строк → CSS-селектор(ы)
  // элемента(ов) внутри активной панели (скроллим к центру, подсвечиваем объединение).
  target: 'nav' | string | string[]
  title: string
  text: string
  card?: 'top' | 'bottom' // принудительное положение карточки (иначе авто)
  interactive?: boolean   // пропускать события сквозь оверлей (юзер взаимодействует с элементом)
}

const STEPS: Step[] = [
  { tab: 'medications', target: ['.mlist-add-btn', '.mlist-card'], card: 'bottom', title: 'Аптечка',
    text: 'Здесь все препараты. Добавляйте новые кнопкой «+» сверху. Для примера мы уже добавили демо-препарат «Счастьепин».' },
  { tab: 'dashboard', target: '.mlist-card', card: 'bottom', interactive: true, title: 'Приёмы',
    text: 'Экран дня. Отмечайте принятые приёмы — сдвиньте зелёный бегунок вправо прямо сейчас на «Счастьепине».' },
  { tab: 'stats', target: '.streak-card', card: 'bottom', title: 'Прогресс',
    text: 'Серия без пропусков — сколько дней подряд вы принимаете препараты вовремя.' },
  { tab: 'stats', target: '#tour-reports', title: 'Отчёты',
    text: 'Выгрузка PDF: расписание на неделю, история приёмов, отчёт для врача — файл придёт прямо в чат с ботом.' },
  { tab: 'settings', target: 'nav', title: 'Настройки',
    text: 'Напоминания, тема оформления, часовой пояс и забота о близких.' },
  { tab: 'settings', target: '#tour-care-section', card: 'top', title: 'Забота',
    text: 'Режим «Забота»: следите за приёмами близких и ведите их аптечку — или поделитесь своим кодом, чтобы кто-то приглядывал за вами.' },
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

export default function OnboardingTour({
  onClose,
  onNavigate,
  onStart,
}: {
  onClose: () => void
  onNavigate: (p: NavPage) => void
  onStart?: () => void // вызывается один раз при запуске тура (создание демо-препарата)
}) {
  const [step, setStep] = useState(0)
  const [rect, setRect] = useState<Rect | null>(null)      // контент (in-page)
  const [navRect, setNavRect] = useState<Rect | null>(null) // пункт нав-бара текущей вкладки
  const [succeeded, setSucceeded] = useState(false)        // интерактивный шаг: действие выполнено
  const lastTab = useRef<NavPage | null>(null)
  const cur = STEPS[step]
  const isNav = cur.target === 'nav'

  // Запуск тура: создаём демо-препарат + принудительно сбрасываем положение окон
  // (скролл всех панелей) — иначе элемент шага может быть вне видимой зоны.
  useEffect(() => {
    onStart?.()
    document.querySelectorAll('.tab-panel').forEach((p) => { (p as HTMLElement).scrollTop = 0 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    onNavigate(cur.tab)
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSucceeded(false)
    const tabChanged = lastTab.current !== cur.tab
    lastTab.current = cur.tab
    let cancelled = false
    let raf = 0
    let takenPoll = 0
    const panelIdx = NAV_ORDER.indexOf(cur.tab)

    const rectOf = (el: HTMLElement): Rect => {
      const x = el.getBoundingClientRect()
      return { left: x.left, top: x.top, width: x.width, height: x.height }
    }

    // Пункт нав-бара текущей вкладки (статичен) — подсвечиваем всегда, параллельно
    // с контентом (вторая «дырка» маски).
    const measureNav = () => {
      if (cancelled) return
      const items = document.querySelectorAll('.bottom-nav .nav-item')
      const navEl = items[panelIdx] as HTMLElement | undefined
      const icon = (navEl?.querySelector('svg') as unknown as HTMLElement | null) ?? navEl ?? null
      setNavRect(icon ? rectOf(icon) : null)
    }

    const getContentEls = (): HTMLElement[] => {
      const panel = document.querySelectorAll('.tab-panel')[panelIdx] as HTMLElement | undefined
      const root: ParentNode = panel ?? document
      const sels = Array.isArray(cur.target) ? cur.target : [cur.target as string]
      return sels
        .map((s) => root.querySelector(s) as HTMLElement | null)
        .filter((e): e is HTMLElement => !!e)
    }

    const commitContent = (els: HTMLElement[]) => {
      if (cancelled) return
      if (!els.length) { setRect(null); return }
      let l = Infinity, t = Infinity, r = -Infinity, b = -Infinity
      els.forEach((e) => {
        const x = e.getBoundingClientRect()
        l = Math.min(l, x.left); t = Math.min(t, x.top)
        r = Math.max(r, x.right); b = Math.max(b, x.bottom)
      })
      setRect({ left: l, top: t, width: r - l, height: b - t })
    }

    // Поллим появление элемента (смена вкладки / дозагрузка демо-мед). Скролл —
    // МГНОВЕННЫЙ (behavior:'auto'): подсветка не гонится за анимацией = нет лага.
    const tryMeasure = (deadline: number) => {
      if (cancelled) return
      const els = getContentEls()
      if (els.length) {
        els[0].scrollIntoView({ block: 'center', behavior: 'auto' })
        commitContent(els)
        raf = requestAnimationFrame(() => { if (!cancelled) { commitContent(getContentEls()); measureNav() } })
        return
      }
      if (Date.now() < deadline) raf = requestAnimationFrame(() => tryMeasure(deadline))
      else setRect(null)
    }

    const run = () => {
      measureNav()
      if (isNav) { setRect(null); return }
      tryMeasure(Date.now() + 1800)
    }

    // Интерактивный шаг: поллим панель на появление принятой карточки → «Отлично!».
    // Поллинг (а не observer одной ноды) устойчив к ре-рендеру/реордеру карточки.
    if (cur.interactive) {
      takenPoll = window.setInterval(() => {
        const panel = document.querySelectorAll('.tab-panel')[panelIdx] as HTMLElement | undefined
        if (panel?.querySelector('.mlist-card--taken')) {
          setSucceeded(true)
          clearInterval(takenPoll)
        }
      }, 300)
    }

    // Ждём оседания translateX вкладки ТОЛЬКО при смене таба (анимация 0.28с).
    const settle = isNav ? 0 : (tabChanged ? 320 : 30)
    const start = window.setTimeout(run, settle)
    const onResize = () => { measureNav(); if (!isNav) commitContent(getContentEls()) }
    window.addEventListener('resize', onResize)
    return () => {
      cancelled = true
      clearTimeout(start)
      cancelAnimationFrame(raf)
      clearInterval(takenPoll)
      window.removeEventListener('resize', onResize)
    }
  }, [step, cur.tab, cur.target, cur.interactive, isNav, onNavigate])

  const finish = () => {
    localStorage.setItem(KEY, '1')
    onNavigate('dashboard')
    onClose()
  }
  const next = () => (step < STEPS.length - 1 ? setStep((s) => s + 1) : finish())
  const back = () => setStep((s) => Math.max(0, s - 1))

  const cardPlace = cur.card ?? (rect && rect.top + rect.height / 2 > window.innerHeight * 0.55 ? 'top' : 'bottom')

  // Дырки маски: пункт нав-бара (pad 13) + контентный элемент (pad 8). Несколько
  // дырок реализованы через SVG-маску (box-shadow не складывается для 2+ отверстий).
  const RADIUS = 14
  const holes: { left: number; top: number; width: number; height: number }[] = []
  if (navRect) holes.push({ left: navRect.left - 13, top: navRect.top - 13, width: navRect.width + 26, height: navRect.height + 26 })
  if (rect && !isNav) {
    // Кламп контентной дырки в видимую зону (над плавающим нав-баром / под верхом),
    // иначе высокие/нижние блоки (Отчёты, Забота) вылезают за границы экрана.
    const vh = window.innerHeight, vw = window.innerWidth
    const SAFE_TOP = 8, NAV_RESERVE = 96
    const l = Math.max(4, rect.left - 8)
    const t = Math.max(SAFE_TOP, rect.top - 8)
    const r = Math.min(vw - 4, rect.left + rect.width + 8)
    const b = Math.min(vh - NAV_RESERVE, rect.top + rect.height + 8)
    if (b > t && r > l) holes.push({ left: l, top: t, width: r - l, height: b - t })
  }

  return (
    <div className={`tour-overlay${cur.interactive ? ' tour-overlay--interactive' : ''}`} onClick={cur.interactive ? undefined : next}>
      <svg className="tour-mask" width="100%" height="100%" preserveAspectRatio="none">
        <defs>
          <mask id="tour-hole-mask">
            <rect x="0" y="0" width="100%" height="100%" fill="white" />
            {holes.map((h, i) => (
              <rect key={i} x={h.left} y={h.top} width={h.width} height={h.height} rx={RADIUS} ry={RADIUS} fill="black" />
            ))}
          </mask>
        </defs>
        <rect x="0" y="0" width="100%" height="100%" fill="rgba(0,0,0,0.72)" mask="url(#tour-hole-mask)" />
      </svg>
      {holes.map((h, i) => (
        <div
          key={i}
          className="tour-ring"
          style={{ left: h.left, top: h.top, width: h.width, height: h.height, borderRadius: RADIUS }}
        />
      ))}
      <div className={`tour-card${cardPlace === 'top' ? ' tour-card--top' : ''}`} onClick={(e) => e.stopPropagation()}>
        <div className="tour-step-count">{step + 1} / {STEPS.length}</div>
        <h3 className="tour-title">{cur.title}</h3>
        <p className="tour-text">
          {cur.text}
          {cur.interactive && succeeded && <span className="tour-success"> Отлично!</span>}
        </p>
        <div className="tour-actions">
          <button type="button" className="tour-skip" onClick={finish}>Пропустить</button>
          <div className="tour-nav-btns">
            {step > 0 && (
              <button type="button" className="tour-back" onClick={back}>Назад</button>
            )}
            <button type="button" className="tour-next" onClick={next}>
              {step < STEPS.length - 1 ? 'Далее' : 'Понятно'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
