import { Lightbulb, Zap, ZapOff, Power } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Badge } from '../components/ui/badge'
import { useAppState } from '../components/layout/Layout'
import { api } from '../api/client'
import { cn } from '../lib/utils'
import { useState } from 'react'

const SHOWCASE_COUNT = 8

function ShowcaseCard({
  id,
  forced,
  onClick,
  loading,
}: {
  id: number
  forced: boolean
  onClick: () => void
  loading: boolean
}) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={cn(
        'relative flex flex-col items-center gap-3 rounded-xl border p-4 transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 disabled:cursor-not-allowed',
        forced
          ? 'border-yellow-400 bg-yellow-50 dark:bg-yellow-950/30 shadow-md shadow-yellow-100 dark:shadow-yellow-900/20'
          : 'border-border bg-card hover:bg-accent hover:border-primary/30'
      )}
    >
      {forced && (
        <div className="absolute -top-1.5 -right-1.5 h-3.5 w-3.5 rounded-full bg-yellow-500 shadow-[0_0_8px_rgba(234,179,8,0.6)]" />
      )}
      <Lightbulb
        className={cn(
          'h-8 w-8 transition-colors',
          forced ? 'text-yellow-500 fill-yellow-400' : 'text-muted-foreground'
        )}
      />
      <div className="text-center">
        <p className={cn(
          'text-sm font-semibold',
          forced ? 'text-yellow-700 dark:text-yellow-400' : 'text-foreground'
        )}>
          #{id}
        </p>
        <p className={cn(
          'text-xs',
          forced ? 'text-yellow-600 dark:text-yellow-500' : 'text-muted-foreground'
        )}>
          {forced ? 'Forced' : 'Auto'}
        </p>
      </div>
    </button>
  )
}

export default function ControlPage() {
  const { state } = useAppState()
  const [loadingIds, setLoadingIds] = useState<Set<number>>(new Set())
  const [loadingAll, setLoadingAll] = useState(false)
  const [loadingLight, setLoadingLight] = useState(false)

  const handleShowcaseToggle = async (id: number) => {
    setLoadingIds(prev => new Set(prev).add(id))
    try {
      if (state.showcase_forced.includes(id)) {
        await api.showcaseForceOff([id])
      } else {
        await api.showcaseForceOn([id])
      }
    } catch (err) {
      console.error('Failed to toggle showcase', err)
    } finally {
      setLoadingIds(prev => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
    }
  }

  const handleAllOn = async () => {
    setLoadingAll(true)
    try {
      await api.showcaseForceOn(null)
    } catch (err) {
      console.error('Failed to force all on', err)
    } finally {
      setLoadingAll(false)
    }
  }

  const handleAllOff = async () => {
    setLoadingAll(true)
    try {
      await api.showcaseForceOff(null)
    } catch (err) {
      console.error('Failed to force all off', err)
    } finally {
      setLoadingAll(false)
    }
  }

  const handleLightOn = async () => {
    setLoadingLight(true)
    try {
      await api.lightForceOn()
    } catch (err) {
      console.error('Failed to force light on', err)
    } finally {
      setLoadingLight(false)
    }
  }

  const handleLightOff = async () => {
    setLoadingLight(true)
    try {
      await api.lightForceOff()
    } catch (err) {
      console.error('Failed to force light off', err)
    } finally {
      setLoadingLight(false)
    }
  }

  const forcedCount = state.showcase_forced.length

  return (
    <div className="space-y-6">
      {/* Showcases section */}
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="space-y-1">
              <CardTitle className="flex items-center gap-2">
                <Lightbulb className="h-5 w-5" />
                Showcases
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                {forcedCount > 0
                  ? `${forcedCount} of ${SHOWCASE_COUNT} forced on`
                  : 'All showcases in auto mode'}
              </p>
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={handleAllOn}
                disabled={loadingAll}
                className="gap-1.5"
              >
                <Zap className="h-3.5 w-3.5" />
                Force All ON
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={handleAllOff}
                disabled={loadingAll}
                className="gap-1.5"
              >
                <ZapOff className="h-3.5 w-3.5" />
                Force All OFF
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-4 gap-3 sm:grid-cols-4 md:grid-cols-8">
            {Array.from({ length: SHOWCASE_COUNT }, (_, i) => i + 1).map(id => (
              <ShowcaseCard
                key={id}
                id={id}
                forced={state.showcase_forced.includes(id)}
                onClick={() => handleShowcaseToggle(id)}
                loading={loadingIds.has(id) || loadingAll}
              />
            ))}
          </div>
          {forcedCount > 0 && (
            <div className="mt-4 flex items-center gap-2">
              <p className="text-xs text-muted-foreground">Forced showcases:</p>
              <div className="flex flex-wrap gap-1">
                {state.showcase_forced.sort((a, b) => a - b).map(id => (
                  <Badge key={id} variant="default" className="text-xs">#{id}</Badge>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* General Light section */}
      <Card className={cn(
        'transition-colors duration-300',
        state.light_forced && 'border-yellow-400 bg-yellow-50/50 dark:bg-yellow-950/20'
      )}>
        <CardHeader>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="space-y-1">
              <CardTitle className="flex items-center gap-2">
                <Power className={cn('h-5 w-5', state.light_forced && 'text-yellow-500')} />
                General Light
                {state.light_forced && (
                  <Badge className="ml-1 bg-yellow-500 text-white">FORCED ON</Badge>
                )}
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                {state.light_forced
                  ? 'Light is currently forced ON — will stay on regardless of automation'
                  : 'Light is in automatic mode'}
              </p>
            </div>
            <div className="flex gap-2">
              <Button
                onClick={handleLightOn}
                disabled={loadingLight || state.light_forced}
                className="gap-1.5"
              >
                <Zap className="h-4 w-4" />
                Force ON
              </Button>
              <Button
                variant="outline"
                onClick={handleLightOff}
                disabled={loadingLight || !state.light_forced}
                className="gap-1.5"
              >
                <ZapOff className="h-4 w-4" />
                Force OFF
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-6">
            <div className={cn(
              'flex h-20 w-20 items-center justify-center rounded-full border-4 transition-all duration-300',
              state.light_forced
                ? 'border-yellow-400 bg-yellow-100 dark:bg-yellow-900/40 shadow-lg shadow-yellow-200 dark:shadow-yellow-900/30'
                : 'border-muted bg-muted'
            )}>
              <Power className={cn(
                'h-8 w-8 transition-colors',
                state.light_forced ? 'text-yellow-600 dark:text-yellow-400' : 'text-muted-foreground'
              )} />
            </div>
            <div className="space-y-1">
              <p className="text-sm font-medium">
                Status: <span className={state.light_forced ? 'text-yellow-600 dark:text-yellow-400 font-semibold' : 'text-muted-foreground'}>
                  {state.light_forced ? 'Forced ON' : 'Auto'}
                </span>
              </p>
              <p className="text-xs text-muted-foreground">
                Connection: {' '}
                <span className={state.light_connected ? 'text-green-600 dark:text-green-400' : 'text-red-500'}>
                  {state.light_connected ? 'Online' : 'Offline'}
                </span>
              </p>
              <p className="text-xs text-muted-foreground mt-2">
                Click "Force ON" to override automation and keep the light on. Click "Force OFF" to return to automatic mode.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
