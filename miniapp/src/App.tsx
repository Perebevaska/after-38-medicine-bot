import { themeParams, viewport } from '@telegram-apps/sdk-react'
import { refreshTheme } from './theme'
import { useEffect, useRef, useState } from 'react'
import { CalendarHeart, Pill, ChartNoAxesColumnIncreasing, Settings } from 'lucide-react'
import { inTelegram } from './main'
import { useQueryClient } from '@tanstack/react-query'
import { useToday, useMedications, useStatsOverview, useSettings, useCreateDemoMed } from './api/hooks'
import { markAchievementsSeen, useSeenAchievements } from './notifications'
import Dashboard from './pages/Dashboard'
import MedicationList from './pages/MedicationList'
import MedicationForm from './pages/MedicationForm'
import StatsPage from './pages/StatsPage'
import SettingsPage from './pages/SettingsPage'
import OnboardingTour, { shouldShowOnboarding } from './components/OnboardingTour'
import { AchievementToast } from './components/AchievementToast'
import './App.css'

type NavPage = 'dashboard' | 'medications' | 'stats' | 'settings'

function NavBadge({ count }: { count: number }) {
  if (count <= 0) return null
  return <span className="nav-badge">{count > 9 ? '9+' : count}</span>
}

function TodayIcon() {
  const { data } = useToday()
  // AX5: is_due — серверный флаг (TZ аккаунта)
  const pending = data?.filter((i) => i.status === 'pending' && i.is_due).length ?? 0
  return (
    <span className="nav-icon-wrap">
      <CalendarHeart size={22} strokeWidth={1.75} />
      <NavBadge count={pending} />
    </span>
  )
}

function MedsIcon() {
  const { data } = useMedications()
  // завершённые курсы — ждут «Продолжить/Удалить». course_done = COUNT(taken),
  // шлётся всегда при заданном course_total → завершён только при done ≥ total.
  const done = data?.filter((m) => m.course_total != null && (m.course_done ?? 0) >= m.course_total).length ?? 0
  return (
    <span className="nav-icon-wrap">
      <Pill size={22} strokeWidth={1.75} />
      <NavBadge count={done} />
    </span>
  )
}

function StatsIcon() {
  const { data } = useStatsOverview()
  const seen = useSeenAchievements()
  const unlocked = data?.achievements?.unlocked ?? []
  const fresh = unlocked.filter((c) => !seen.includes(c)).length
  return (
    <span className="nav-icon-wrap">
      <ChartNoAxesColumnIncreasing size={22} strokeWidth={1.75} />
      <NavBadge count={fresh} />
    </span>
  )
}

function SettingsIcon() {
  const { data } = useSettings()
  // pending-запросы «Забота»: входящие F7 + входящие F8
  const n = (data?.pending_requests?.length ?? 0) + (data?.pending_viewing_deps?.length ?? 0)
  return (
    <span className="nav-icon-wrap">
      <Settings size={22} strokeWidth={1.75} />
      <NavBadge count={n} />
    </span>
  )
}

function BottomNav({ active, onChange }: { active: NavPage; onChange: (p: NavPage) => void }) {
  return (
    <nav className="bottom-nav" style={{ ['--nav-i' as string]: NAV_PAGES.indexOf(active) }}>
      <button
        type="button"
        className={`nav-item${active === 'dashboard' ? ' nav-item--active' : ''}`}
        onClick={() => onChange('dashboard')}
      >
        <TodayIcon />
        <span className="nav-label">Приёмы</span>
      </button>
      <button
        type="button"
        className={`nav-item${active === 'medications' ? ' nav-item--active' : ''}`}
        onClick={() => onChange('medications')}
      >
        <MedsIcon />
        <span className="nav-label">Аптечка</span>
      </button>
      <button
        type="button"
        className={`nav-item${active === 'stats' ? ' nav-item--active' : ''}`}
        onClick={() => onChange('stats')}
      >
        <StatsIcon />
        <span className="nav-label">Прогресс</span>
      </button>
      <button
        type="button"
        className={`nav-item${active === 'settings' ? ' nav-item--active' : ''}`}
        onClick={() => onChange('settings')}
      >
        <SettingsIcon />
        <span className="nav-label">Настройки</span>
      </button>
    </nav>
  )
}

const NAV_PAGES: NavPage[] = ['dashboard', 'medications', 'stats', 'settings']
const SWIPE_MIN_X = 65
const SWIPE_RATIO = 1.5

type ResetKeys = Record<NavPage, number>

export default function App() {
  const [navPage, setNavPage] = useState<NavPage>('dashboard')
  const [resetKeys] = useState<ResetKeys>({ dashboard: 0, medications: 0, stats: 0, settings: 0 })
  const [editMedId, setEditMedId] = useState<number | undefined>()
  const [editLinkedUserId, setEditLinkedUserId] = useState<number | undefined>()
  const [editForDepShareId, setEditForDepShareId] = useState<number | undefined>()
  const [openSchedule, setOpenSchedule] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [showTour, setShowTour] = useState(shouldShowOnboarding)
  const touchStart = useRef<{ x: number; y: number } | null>(null)
  const qc = useQueryClient()
  const { data: overview } = useStatsOverview()

  // Возврат в приложение (свернул → отметил в TG-чате → вернулся) или показ
  // вкладки после фона: Telegram webview не шлёт надёжный window-focus, поэтому
  // принудительно обновляем server-state по visibilitychange. Закрывает: stale
  // «Приёмы» и непоявившийся pending «Забота» в «Настройках».
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') void qc.invalidateQueries()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [qc])

  // Открытие «Прогресс» → ачивки считаются увиденными (гасит бейдж)
  useEffect(() => {
    if (navPage === 'stats' && overview?.achievements) {
      markAchievementsSeen(overview.achievements.unlocked)
    }
  }, [navPage, overview?.achievements])

  // Тяжёлая статистика помечается stale без рефетча при отметке (чтобы не тормозил
  // слайдер). Освежаем её при фактическом открытии вкладки «Прогресс».
  useEffect(() => {
    if (navPage !== 'stats') return
    qc.invalidateQueries({ queryKey: ['stats-overview'] })
    qc.invalidateQueries({ queryKey: ['streak'] })
    qc.invalidateQueries({ queryKey: ['adherence'] })
  }, [navPage, qc])

  useEffect(() => {
    if (!inTelegram) return

    void themeParams.mount().then(() => { themeParams.bindCssVars(); refreshTheme() })
    void viewport.mount().then(() => {
      viewport.expand()
      viewport.bindCssVars()
    })

    return () => {
      themeParams.unmount()
      viewport.unmount()
    }
  }, [])

  // Демо-препарат «Счастьепин» создаётся при запуске обучения (mount тура),
  // чтобы туру было что показать на «Аптечке»/«Приёмах». Идемпотентно на сервере.
  const createDemo = useCreateDemoMed()

  const handleTouchStart = (e: React.TouchEvent) => {
    const t = e.touches[0]
    touchStart.current = { x: t.clientX, y: t.clientY }
  }

  const handleTouchEnd = (e: React.TouchEvent) => {
    if (!touchStart.current) return
    const t = e.changedTouches[0]
    const dx = t.clientX - touchStart.current.x
    const dy = t.clientY - touchStart.current.y
    touchStart.current = null

    if (Math.abs(dx) < SWIPE_MIN_X) return
    if (Math.abs(dx) < Math.abs(dy) * SWIPE_RATIO) return

    const idx = NAV_PAGES.indexOf(navPage)
    if (dx < 0 && idx < NAV_PAGES.length - 1) setNavPage(NAV_PAGES[idx + 1])
    if (dx > 0 && idx > 0) setNavPage(NAV_PAGES[idx - 1])
  }

  const openForm = (editId?: number, linkedUserId?: number, forDepShareId?: number, openSchedule?: boolean) => {
    setEditMedId(editId)
    setEditLinkedUserId(linkedUserId)
    setEditForDepShareId(forDepShareId)
    setOpenSchedule(!!openSchedule)
    setShowForm(true)
  }

  const closeForm = () => {
    setShowForm(false)
    setEditMedId(undefined)
    setEditLinkedUserId(undefined)
    setEditForDepShareId(undefined)
    setOpenSchedule(false)
  }

  if (showForm) {
    return <MedicationForm editId={editMedId} linkedUserId={editLinkedUserId} forDepShareId={editForDepShareId} openSchedule={openSchedule} onBack={closeForm} />
  }

  const activeIdx = NAV_PAGES.indexOf(navPage)

  return (
    <div onTouchStart={handleTouchStart} onTouchEnd={handleTouchEnd}>
      <div className="tabs-outer">
        {NAV_PAGES.map((page, i) => (
          <div
            key={page}
            className="tab-panel"
            style={{ transform: `translateX(${(i - activeIdx) * 100}%)` }}
          >
            {page === 'dashboard' && <Dashboard key={resetKeys.dashboard} onNavigate={setNavPage} />}
            {page === 'medications' && (
              <MedicationList key={resetKeys.medications} onAdd={(uid, sid) => openForm(undefined, uid, sid)} onEdit={(id, uid, sid) => openForm(id, uid, sid)} onSchedule={(id, uid, sid) => openForm(id, uid, sid, true)} />
            )}
            {page === 'stats' && <StatsPage key={resetKeys.stats} />}
            {page === 'settings' && <SettingsPage key={resetKeys.settings} onReplayTour={() => { setNavPage('dashboard'); setShowTour(true) }} />}
          </div>
        ))}
      </div>
      <BottomNav
        active={navPage}
        onChange={(p) => {
          if (p === navPage) {
            // Повторный тап по активной вкладке → плавный скролл панели наверх
            // (без remount: переключение/возврат сохраняют позицию скролла).
            const panel = document.querySelectorAll<HTMLElement>('.tab-panel')[NAV_PAGES.indexOf(p)]
            panel?.scrollTo({ top: 0, behavior: 'smooth' })
          } else {
            setNavPage(p)
          }
        }}
      />
      {showTour && !showForm && <OnboardingTour onClose={() => setShowTour(false)} onNavigate={setNavPage} onStart={() => createDemo.mutate()} />}
      <AchievementToast />
    </div>
  )
}
