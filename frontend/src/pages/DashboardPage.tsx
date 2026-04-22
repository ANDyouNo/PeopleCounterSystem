import React, { useState } from 'react'
import { Users, Activity, Cpu, TrendingUp, Camera, Wifi, WifiOff, Clock, Eye } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { useAppState } from '../components/layout/Layout'
import { cn } from '../lib/utils'

function StatCard({
  title,
  value,
  icon: Icon,
  description,
  highlight,
  unit,
}: {
  title: string
  value: string | number
  icon: React.ElementType
  description?: string
  highlight?: boolean
  unit?: string
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className={cn(
          'text-3xl font-bold tracking-tight',
          highlight ? 'text-green-500' : 'text-foreground'
        )}>
          {value}
          {unit && <span className="ml-1 text-lg font-normal text-muted-foreground">{unit}</span>}
        </div>
        {description && (
          <p className="mt-1 text-xs text-muted-foreground">{description}</p>
        )}
      </CardContent>
    </Card>
  )
}

function StatusIndicator({ label, online }: { label: string; online: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm font-medium">{label}</span>
      <div className="flex items-center gap-2">
        <div className={cn(
          'h-2.5 w-2.5 rounded-full',
          online ? 'bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]' : 'bg-gray-400'
        )} />
        <span className={cn(
          'text-sm font-medium',
          online ? 'text-green-600 dark:text-green-400' : 'text-muted-foreground'
        )}>
          {online ? 'Online' : 'Offline'}
        </span>
      </div>
    </div>
  )
}

export default function DashboardPage() {
  const { state } = useAppState()
  const [cameraError, setCameraError] = useState(false)

  return (
    <div className="space-y-6">
      {/* Top stat cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          title="People Now"
          value={state.people_now}
          icon={Users}
          highlight={state.people_now > 0}
          description={state.people_now > 0 ? 'Currently detected' : 'Area is empty'}
        />
        <StatCard
          title="Today Visits"
          value={state.today_visits}
          icon={Activity}
          description="Unique visits today"
        />
        <StatCard
          title="Session Unique"
          value={state.total_unique}
          icon={Eye}
          description="Total tracked IDs"
        />
        <StatCard
          title="FPS"
          value={state.fps.toFixed(1)}
          icon={Cpu}
          description={`Inference: ${state.inference_ms.toFixed(1)}ms`}
        />
      </div>

      {/* Video + ESP status */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Live video (2/3) */}
        <Card className="lg:col-span-2">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2 text-base">
                <Camera className="h-4 w-4" />
                Live Feed
              </CardTitle>
              <Badge variant={cameraError ? 'destructive' : 'default'}>
                {cameraError ? 'Offline' : 'Live'}
              </Badge>
            </div>
          </CardHeader>
          <CardContent>
            <div className="relative w-full overflow-hidden rounded-md bg-black" style={{ aspectRatio: '16/9' }}>
              {!cameraError ? (
                <img
                  src="http://localhost:8000/stream/video"
                  alt="Live camera feed"
                  className="h-full w-full object-contain"
                  onError={() => setCameraError(true)}
                  onLoad={() => setCameraError(false)}
                />
              ) : (
                <div className="flex h-full w-full flex-col items-center justify-center gap-3 text-gray-500">
                  <Camera className="h-12 w-12 opacity-40" />
                  <div className="text-center">
                    <p className="text-sm font-medium">Camera Offline</p>
                    <p className="text-xs opacity-70">Unable to connect to video stream</p>
                  </div>
                  <button
                    onClick={() => setCameraError(false)}
                    className="mt-2 rounded-md bg-gray-800 px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700 transition-colors"
                  >
                    Retry
                  </button>
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* ESP status (1/3) */}
        <div className="space-y-4">
          {/* Showcases ESP */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                {state.showcase_connected ? (
                  <Wifi className="h-4 w-4 text-green-500" />
                ) : (
                  <WifiOff className="h-4 w-4 text-muted-foreground" />
                )}
                Showcases ESP
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <StatusIndicator label="Connection" online={state.showcase_connected} />
              <div>
                <p className="mb-2 text-xs font-medium text-muted-foreground">Forced ON</p>
                {state.showcase_forced.length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {state.showcase_forced.map(id => (
                      <Badge key={id} variant="default" className="text-xs">
                        #{id}
                      </Badge>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">None forced</p>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Light ESP */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                {state.light_connected ? (
                  <Wifi className="h-4 w-4 text-green-500" />
                ) : (
                  <WifiOff className="h-4 w-4 text-muted-foreground" />
                )}
                General Light ESP
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <StatusIndicator label="Connection" online={state.light_connected} />
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">Light Forced</span>
                <Badge variant={state.light_forced ? 'default' : 'secondary'}>
                  {state.light_forced ? 'ON' : 'Off'}
                </Badge>
              </div>
            </CardContent>
          </Card>

          {/* People count info */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <TrendingUp className="h-4 w-4" />
                Today Summary
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Clock className="h-3.5 w-3.5" />
                  Minutes today
                </div>
                <span className="text-sm font-semibold">
                  {state.today_minutes.toFixed(1)}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Users className="h-3.5 w-3.5" />
                  Peak today
                </div>
                <span className="text-sm font-semibold">{state.max_people_today}</span>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Bottom today stats */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card className="bg-gradient-to-br from-blue-50 to-blue-100/50 dark:from-blue-950/50 dark:to-blue-900/20 border-blue-200 dark:border-blue-800">
          <CardContent className="pt-6">
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-blue-100 dark:bg-blue-900">
                <Activity className="h-6 w-6 text-blue-600 dark:text-blue-400" />
              </div>
              <div>
                <p className="text-2xl font-bold text-blue-700 dark:text-blue-300">{state.today_visits}</p>
                <p className="text-sm text-blue-600/80 dark:text-blue-400/80">Today Visits</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-gradient-to-br from-purple-50 to-purple-100/50 dark:from-purple-950/50 dark:to-purple-900/20 border-purple-200 dark:border-purple-800">
          <CardContent className="pt-6">
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-purple-100 dark:bg-purple-900">
                <Clock className="h-6 w-6 text-purple-600 dark:text-purple-400" />
              </div>
              <div>
                <p className="text-2xl font-bold text-purple-700 dark:text-purple-300">
                  {state.today_minutes.toFixed(1)}
                </p>
                <p className="text-sm text-purple-600/80 dark:text-purple-400/80">Minutes Today</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-gradient-to-br from-orange-50 to-orange-100/50 dark:from-orange-950/50 dark:to-orange-900/20 border-orange-200 dark:border-orange-800">
          <CardContent className="pt-6">
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-orange-100 dark:bg-orange-900">
                <TrendingUp className="h-6 w-6 text-orange-600 dark:text-orange-400" />
              </div>
              <div>
                <p className="text-2xl font-bold text-orange-700 dark:text-orange-300">{state.max_people_today}</p>
                <p className="text-sm text-orange-600/80 dark:text-orange-400/80">Peak Today</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
