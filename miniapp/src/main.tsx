import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { init, isTMA, restoreInitData, retrieveRawInitData } from '@telegram-apps/sdk-react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ErrorBoundary } from './components/ErrorBoundary'
import { setInitData } from './api/client'
import './index.css'
import App from './App.tsx'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 30_000 },
  },
})

export const inTelegram = isTMA()

if (inTelegram) {
  init()
  restoreInitData()
  const raw = retrieveRawInitData()
  if (raw) setInitData(raw)
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
)
