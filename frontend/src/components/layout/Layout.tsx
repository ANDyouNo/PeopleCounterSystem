import { Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { ThemeToggle } from '../ThemeToggle'
import { useWebSocket } from '../../hooks/useWebSocket'
import type { AppState } from '../../api/client'
import { createContext, useContext } from 'react'

// Determine WS URL based on environment
const WS_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`

interface AppStateContextValue {
  state: AppState
  connected: boolean
}

export const AppStateContext = createContext<AppStateContextValue>({
  state: {
    people_now: 0,
    fps: 0,
    inference_ms: 0,
    total_unique: 0,
    today_visits: 0,
    today_minutes: 0,
    max_people_today: 0,
    showcase_connected: false,
    light_connected: false,
    showcase_forced: [],
    light_forced: false,
  },
  connected: false,
})

export function useAppState() {
  return useContext(AppStateContext)
}

const PAGE_TITLES: Record<string, string> = {
  '/': 'Dashboard',
  '/control': 'Control',
  '/analytics': 'Analytics',
  '/settings': 'Settings',
}

export default function Layout() {
  const { state, connected } = useWebSocket(WS_URL)
  const location = useLocation()
  const title = PAGE_TITLES[location.pathname] ?? 'People Counter'

  return (
    <AppStateContext.Provider value={{ state, connected }}>
      <div className="flex h-screen bg-background overflow-hidden">
        <Sidebar connected={connected} />

        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Top bar */}
          <header className="flex items-center justify-between border-b bg-card px-6 py-4">
            <h1 className="text-lg font-semibold">{title}</h1>
            <div className="flex items-center gap-2">
              <ThemeToggle />
            </div>
          </header>

          {/* Page content */}
          <main className="flex-1 overflow-y-auto p-6">
            <Outlet />
          </main>
        </div>
      </div>
    </AppStateContext.Provider>
  )
}
