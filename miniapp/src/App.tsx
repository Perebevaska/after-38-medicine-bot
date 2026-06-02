import { themeParams, viewport } from '@telegram-apps/sdk-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { inTelegram } from './main'
import Dashboard from './pages/Dashboard'
import MedicationList from './pages/MedicationList'
import MedicationForm from './pages/MedicationForm'
import StockPage from './pages/StockPage'
import './App.css'

type NavPage = 'dashboard' | 'medications' | 'stock'

const WISHES = [
  'Выздоравливай ❤️',
  'Всё будет хорошо ✨',
  'Ты справишься 💪',
  'Береги себя 🌸',
  'Мы с тобой 🤍',
  'Ты молодец 🌟',
  'Маленькие шаги — тоже победа 🌱',
  'Будь здоров(а) 🍀',
  'Ты не один(а) 💙',
  'Всё под контролем 🌿',
  'Верь в себя 🌈',
  'Забота о себе — это важно 🕊️',
  'Сегодня станет лучше 🌤️',
  'Ты в безопасности 🫶',
  'Каждый день — маленькая победа 🎯',
]

function SplashScreen({ onDone }: { onDone: () => void }) {
  const [fading, setFading] = useState(false)
  const wish = useMemo(() => WISHES[Math.floor(Math.random() * WISHES.length)], [])

  useEffect(() => {
    const t1 = setTimeout(() => setFading(true), 1500)
    const t2 = setTimeout(onDone, 2000)
    return () => { clearTimeout(t1); clearTimeout(t2) }
  }, [onDone])

  return (
    <div className={`splash${fading ? ' splash--out' : ''}`}>
      <p className="splash-wish">{wish}</p>
    </div>
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
        <span className="nav-icon">📅</span>
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
    </nav>
  )
}

const NAV_PAGES: NavPage[] = ['dashboard', 'medications', 'stock']
const SWIPE_MIN_X = 65
const SWIPE_RATIO = 1.5

export default function App() {
  const [navPage, setNavPage] = useState<NavPage>('dashboard')
  const [editMedId, setEditMedId] = useState<number | undefined>()
  const [showForm, setShowForm] = useState(false)
  const [showSplash, setShowSplash] = useState(true)
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
      {showSplash && <SplashScreen onDone={() => setShowSplash(false)} />}
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
          </div>
        ))}
      </div>
      <BottomNav active={navPage} onChange={setNavPage} />
    </div>
  )
}
