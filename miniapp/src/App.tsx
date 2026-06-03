import { themeParams, viewport } from '@telegram-apps/sdk-react'
import { useEffect, useRef, useState } from 'react'
import { CalendarHeart, Pill, ChartNoAxesColumnIncreasing, Settings } from 'lucide-react'
import { inTelegram } from './main'
import { useToday } from './api/hooks'
import Dashboard from './pages/Dashboard'
import MedicationList from './pages/MedicationList'
import MedicationForm from './pages/MedicationForm'
import StatsPage from './pages/StatsPage'
import SettingsPage from './pages/SettingsPage'
import './App.css'

type NavPage = 'dashboard' | 'medications' | 'stats' | 'settings'

function TodayIcon() {
  const { data } = useToday()
  // AX5: is_due — серверный флаг (TZ аккаунта)
  const pending = data?.filter((i) => i.status === 'pending' && i.is_due).length ?? 0
  return (
    <span className="nav-icon-wrap">
      <CalendarHeart size={22} strokeWidth={1.75} />
      {pending > 0 && <span className="nav-badge">{pending > 9 ? '9+' : pending}</span>}
    </span>
  )
}

function BottomNav({ active, onChange }: { active: NavPage; onChange: (p: NavPage) => void }) {
  return (
    <nav className="bottom-nav">
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
        <Pill size={22} strokeWidth={1.75} />
        <span className="nav-label">Аптечка</span>
      </button>
      <button
        type="button"
        className={`nav-item${active === 'stats' ? ' nav-item--active' : ''}`}
        onClick={() => onChange('stats')}
      >
        <ChartNoAxesColumnIncreasing size={22} strokeWidth={1.75} />
        <span className="nav-label">Прогресс</span>
      </button>
      <button
        type="button"
        className={`nav-item${active === 'settings' ? ' nav-item--active' : ''}`}
        onClick={() => onChange('settings')}
      >
        <Settings size={22} strokeWidth={1.75} />
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
  const [resetKeys, setResetKeys] = useState<ResetKeys>({ dashboard: 0, medications: 0, stats: 0, settings: 0 })
  const [editMedId, setEditMedId] = useState<number | undefined>()
  const [editLinkedUserId, setEditLinkedUserId] = useState<number | undefined>()
  const [editForDepShareId, setEditForDepShareId] = useState<number | undefined>()
  const [showForm, setShowForm] = useState(false)
  const touchStart = useRef<{ x: number; y: number } | null>(null)

  useEffect(() => {
    if (!inTelegram) return

    void themeParams.mount().then(() => themeParams.bindCssVars())
    void viewport.mount().then(() => {
      viewport.expand()
      viewport.bindCssVars()
    })

    return () => {
      themeParams.unmount()
      viewport.unmount()
    }
  }, [])

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

  const openForm = (editId?: number, linkedUserId?: number, forDepShareId?: number) => {
    setEditMedId(editId)
    setEditLinkedUserId(linkedUserId)
    setEditForDepShareId(forDepShareId)
    setShowForm(true)
  }

  const closeForm = () => {
    setShowForm(false)
    setEditMedId(undefined)
    setEditLinkedUserId(undefined)
    setEditForDepShareId(undefined)
  }

  if (showForm) {
    return <MedicationForm editId={editMedId} linkedUserId={editLinkedUserId} forDepShareId={editForDepShareId} onBack={closeForm} />
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
            {page === 'dashboard' && <Dashboard key={resetKeys.dashboard} />}
            {page === 'medications' && (
              <MedicationList key={resetKeys.medications} onAdd={(uid, sid) => openForm(undefined, uid, sid)} onEdit={(id, uid, sid) => openForm(id, uid, sid)} />
            )}
            {page === 'stats' && <StatsPage key={resetKeys.stats} />}
            {page === 'settings' && <SettingsPage key={resetKeys.settings} />}
          </div>
        ))}
      </div>
      <BottomNav
        active={navPage}
        onChange={(p) => {
          if (p === navPage) {
            setResetKeys((k) => ({ ...k, [p]: k[p] + 1 }))
          } else {
            setNavPage(p)
          }
        }}
      />
    </div>
  )
}
