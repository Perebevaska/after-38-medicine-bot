import { themeParams, viewport } from '@telegram-apps/sdk-react'
import { useEffect } from 'react'
import { inTelegram } from './main'
import Dashboard from './pages/Dashboard'
import './App.css'

export default function App() {
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

  return <Dashboard />
}
