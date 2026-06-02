import { themeParams, viewport } from '@telegram-apps/sdk-react'
import { useEffect, useRef, useState } from 'react'
import { inTelegram } from './main'
import { useToday } from './api/hooks'
import Dashboard from './pages/Dashboard'
import MedicationList from './pages/MedicationList'
import MedicationForm from './pages/MedicationForm'
import StockPage from './pages/StockPage'
import StatsPage from './pages/StatsPage'
import SettingsPage from './pages/SettingsPage'
import './App.css'

type NavPage = 'dashboard' | 'medications' | 'stock' | 'stats' | 'settings'

function TodayIcon() {
  const day = new Date().getDate().toString().padStart(2, '0')
  const { data } = useToday()
  const pending = data?.filter((i) => i.status === 'pending').length ?? 0
  return (
    <span className="nav-icon nav-icon--date-wrap">
      <span className="nav-icon--date">{day}</span>
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
        <span className="nav-label">Сегодня</span>
      </button>
      <button
        type="button"
        className={`nav-item${active === 'medications' ? ' nav-item--active' : ''}`}
        onClick={() => onChange('medications')}
      >
        <span className="nav-icon">💊</span>
        <span className="nav-label">Лекарства</span>
      </button>
      <button
        type="button"
        className={`nav-item${active === 'stock' ? ' nav-item--active' : ''}`}
        onClick={() => onChange('stock')}
      >
        <span className="nav-icon">📦</span>
        <span className="nav-label">Запас</span>
      </button>
      <button
        type="button"
        className={`nav-item${active === 'stats' ? ' nav-item--active' : ''}`}
        onClick={() => onChange('stats')}
      >
        <span className="nav-icon">📊</span>
        <span className="nav-label">Статистика</span>
      </button>
      <button
        type="button"
        className={`nav-item${active === 'settings' ? ' nav-item--active' : ''}`}
        onClick={() => onChange('settings')}
      >
        <span className="nav-icon">⚙️</span>
        <span className="nav-label">Настройки</span>
      </button>
    </nav>
  )
}

const NAV_PAGES: NavPage[] = ['dashboard', 'medications', 'stock', 'stats', 'settings']
const SWIPE_MIN_X = 65
const SWIPE_RATIO = 1.5

export default function App() {
  const [navPage, setNavPage] = useState<NavPage>('dashboard')
  const [editMedId, setEditMedId] = useState<number | undefined>()
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

  const openForm = (editId?: number) => {
    setEditMedId(editId)
    setShowForm(true)
  }

  const closeForm = () => {
    setShowForm(false)
    setEditMedId(undefined)
  }

  if (showForm) {
    return <MedicationForm editId={editMedId} onBack={closeForm} />
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
            {page === 'dashboard' && <Dashboard />}
            {page === 'medications' && (
              <MedicationList onAdd={() => openForm()} onEdit={(id) => openForm(id)} />
            )}
            {page === 'stock' && <StockPage />}
            {page === 'stats' && <StatsPage />}
            {page === 'settings' && <SettingsPage />}
          </div>
        ))}
      </div>
      <BottomNav active={navPage} onChange={setNavPage} />
    </div>
  )
}
