import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Sliders, BarChart3, Settings, Camera, ScanLine, Sparkles } from 'lucide-react'
import { cn } from '../../lib/utils'

interface SidebarProps {
  connected: boolean
}

const navItems = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/control', label: 'Control', icon: Sliders, end: false },
  { to: '/analytics', label: 'Analytics', icon: BarChart3, end: false },
  { to: '/zones', label: 'Zones', icon: ScanLine, end: false },
  { to: '/effects', label: 'Effects', icon: Sparkles, end: false },
  { to: '/settings', label: 'Settings', icon: Settings, end: false },
]

export function Sidebar({ connected }: SidebarProps) {
  return (
    <aside className="flex h-full w-64 flex-col border-r bg-card">
      {/* App header */}
      <div className="flex items-center gap-3 border-b px-6 py-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10">
          <Camera className="h-5 w-5 text-primary" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold leading-tight truncate">People Counter</p>
          <p className="text-xs text-muted-foreground">Vision System</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 px-3 py-4">
        {navItems.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Connection status */}
      <div className="border-t px-6 py-4">
        <div className="flex items-center gap-2">
          <div className={cn(
            'h-2 w-2 rounded-full',
            connected ? 'bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.6)]' : 'bg-gray-400'
          )} />
          <span className="text-xs text-muted-foreground">
            {connected ? 'Connected' : 'Disconnected'}
          </span>
        </div>
        <p className="mt-1 text-xs text-muted-foreground/60">WebSocket</p>
      </div>
    </aside>
  )
}
