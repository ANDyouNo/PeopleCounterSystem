import { Sun, Moon, Monitor } from 'lucide-react'
import { useTheme } from '../hooks/useTheme'
import { Button } from './ui/button'
import { cn } from '../lib/utils'

export function ThemeToggle() {
  const { theme, cycleTheme } = useTheme()

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={cycleTheme}
      title={`Theme: ${theme}. Click to cycle.`}
      className="relative"
    >
      <Sun className={cn('h-5 w-5 transition-all', theme === 'light' ? 'opacity-100' : 'opacity-0 absolute')} />
      <Moon className={cn('h-5 w-5 transition-all', theme === 'dark' ? 'opacity-100' : 'opacity-0 absolute')} />
      <Monitor className={cn('h-5 w-5 transition-all', theme === 'system' ? 'opacity-100' : 'opacity-0 absolute')} />
      <span className="sr-only">Toggle theme</span>
    </Button>
  )
}
