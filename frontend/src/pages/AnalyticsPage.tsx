import React, { useEffect, useMemo, useState } from 'react'
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts'
import { Calendar, TrendingUp, Clock, Activity, ChevronLeft, ChevronRight } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card'
import { api, type DailyStat, type HourlyStat } from '../api/client'

// ── Date helpers ─────────────────────────────────────────────────
// Parse "YYYY-MM-DD" in LOCAL time (not UTC) to avoid day-shift in negative-UTC zones.

function parseLocalDate(dateStr: string | null | undefined): Date | null {
  if (!dateStr || typeof dateStr !== 'string') return null
  const parts = dateStr.split('-')
  if (parts.length !== 3) return null
  const [y, m, d] = parts.map(Number)
  if (!y || !m || !d || isNaN(y) || isNaN(m) || isNaN(d)) return null
  return new Date(y, m - 1, d)
}

function formatLabel(dateStr: string | null | undefined): string {
  const d = parseLocalDate(dateStr)
  if (!d) return ''
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function toYMD(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

// ── Mini calendar ────────────────────────────────────────────────

interface MiniCalendarProps {
  selected: string
  onSelect: (d: string) => void
  dotDates: Set<string>
}

const WEEKDAYS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']
const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

function MiniCalendar({ selected, onSelect, dotDates }: MiniCalendarProps) {
  const todayStr = toYMD(new Date())

  const selDate = parseLocalDate(selected) ?? new Date()
  const [viewYear, setViewYear] = useState(selDate.getFullYear())
  const [viewMonth, setViewMonth] = useState(selDate.getMonth())

  // Sync view when selected changes externally
  useEffect(() => {
    const d = parseLocalDate(selected)
    if (d) { setViewYear(d.getFullYear()); setViewMonth(d.getMonth()) }
  }, [selected])

  const prevMonth = () => {
    if (viewMonth === 0) { setViewMonth(11); setViewYear(y => y - 1) }
    else setViewMonth(m => m - 1)
  }
  const nextMonth = () => {
    if (viewMonth === 11) { setViewMonth(0); setViewYear(y => y + 1) }
    else setViewMonth(m => m + 1)
  }

  const cells = useMemo(() => {
    const firstDay = new Date(viewYear, viewMonth, 1).getDay()
    const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate()
    const arr: (number | null)[] = Array(firstDay).fill(null)
    for (let d = 1; d <= daysInMonth; d++) arr.push(d)
    while (arr.length % 7 !== 0) arr.push(null)
    return arr
  }, [viewYear, viewMonth])

  return (
    <div className="rounded-lg border bg-card p-3 w-[17rem] shadow-md select-none">
      {/* Month nav */}
      <div className="flex items-center justify-between mb-3">
        <button onClick={prevMonth} className="rounded p-1 hover:bg-accent transition-colors text-muted-foreground hover:text-foreground">
          <ChevronLeft className="h-4 w-4" />
        </button>
        <span className="text-sm font-semibold">{MONTHS[viewMonth]} {viewYear}</span>
        <button onClick={nextMonth} className="rounded p-1 hover:bg-accent transition-colors text-muted-foreground hover:text-foreground">
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>

      {/* Weekday row */}
      <div className="grid grid-cols-7 mb-1">
        {WEEKDAYS.map(w => (
          <div key={w} className="text-center text-[10px] font-medium text-muted-foreground py-1">{w}</div>
        ))}
      </div>

      {/* Day grid */}
      <div className="grid grid-cols-7 gap-y-0.5">
        {cells.map((day, i) => {
          if (day === null) return <div key={`e-${i}`} />
          const mm = String(viewMonth + 1).padStart(2, '0')
          const dd = String(day).padStart(2, '0')
          const dateStr = `${viewYear}-${mm}-${dd}`
          const isSelected = dateStr === selected
          const isToday = dateStr === todayStr
          const hasData = dotDates.has(dateStr)
          const isFuture = dateStr > todayStr

          return (
            <button
              key={dateStr}
              onClick={() => !isFuture && onSelect(dateStr)}
              disabled={isFuture}
              className={[
                'relative flex flex-col items-center justify-center rounded-md h-8 text-xs font-medium transition-colors',
                isSelected
                  ? 'bg-primary text-primary-foreground'
                  : isToday
                    ? 'bg-accent text-accent-foreground ring-1 ring-primary/40'
                    : isFuture
                      ? 'text-muted-foreground/30 cursor-default'
                      : 'hover:bg-accent text-foreground cursor-pointer',
              ].join(' ')}
            >
              {day}
              {hasData && (
                <span className={[
                  'absolute bottom-0.5 left-1/2 -translate-x-1/2 h-1 w-1 rounded-full',
                  isSelected ? 'bg-primary-foreground/60' : 'bg-primary',
                ].join(' ')} />
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── Summary card ──────────────────────────────────────────────────

function SummaryCard({ title, value, icon: Icon, sub }: {
  title: string; value: string | number; icon: React.ElementType; sub?: string
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        {sub && <p className="text-xs text-muted-foreground mt-1">{sub}</p>}
      </CardContent>
    </Card>
  )
}

const tooltipStyle = {
  backgroundColor: 'hsl(var(--card))',
  border: '1px solid hsl(var(--border))',
  borderRadius: '8px',
  color: 'hsl(var(--foreground))',
}

// ── Page ──────────────────────────────────────────────────────────

export default function AnalyticsPage() {
  const [dailyStats, setDailyStats] = useState<DailyStat[]>([])
  const [hourlyStats, setHourlyStats] = useState<HourlyStat[]>([])
  const [selectedDate, setSelectedDate] = useState<string>(toYMD(new Date()))
  const [days, setDays] = useState(30)
  const [loading, setLoading] = useState(false)
  const [loadingHourly, setLoadingHourly] = useState(false)
  const [calendarOpen, setCalendarOpen] = useState(false)

  useEffect(() => {
    setLoading(true)
    api.getDailyStats(days).then(setDailyStats).catch(console.error).finally(() => setLoading(false))
  }, [days])

  useEffect(() => {
    setLoadingHourly(true)
    api.getHourlyStats(selectedDate).then(setHourlyStats).catch(console.error).finally(() => setLoadingHourly(false))
  }, [selectedDate])

  const totalVisits   = dailyStats.reduce((s, d) => s + (d.visits ?? 0), 0)
  const totalMinutes  = dailyStats.reduce((s, d) => s + (d.total_minutes ?? 0), 0)
  const avgPerDay     = dailyStats.length > 0 ? (totalVisits / dailyStats.length).toFixed(1) : '0'

  // Set of dates that have data — for calendar dots
  const dotDates = useMemo(() => new Set(dailyStats.map(d => d.date).filter(Boolean)), [dailyStats])

  // Chart data — pass raw, use tickFormatter on XAxis (avoids recharts undefined-tick crash)
  const chartData = dailyStats

  // Hourly: fill all 24 slots
  const hourlyFull = Array.from({ length: 24 }, (_, h) =>
    hourlyStats.find(s => s.hour === h) ?? { hour: h, visits: 0, total_minutes: 0, peak_people: 0 }
  )

  const tickInterval = Math.max(0, Math.floor(chartData.length / 8))

  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <SummaryCard title="Total Visits"    value={totalVisits.toLocaleString()} icon={Activity} sub={`Last ${days} days`} />
        <SummaryCard title="Total Minutes"   value={Math.round(totalMinutes).toLocaleString()} icon={Clock} sub={`≈ ${(totalMinutes / 60).toFixed(1)} hours`} />
        <SummaryCard title="Avg Visits / Day" value={avgPerDay} icon={TrendingUp} sub={`Over ${dailyStats.length} days with data`} />
      </div>

      {/* Range buttons */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">Range:</span>
        {[7, 14, 30, 60, 90].map(d => (
          <button
            key={d}
            onClick={() => setDays(d)}
            className={`rounded-md px-3 py-1 text-sm font-medium transition-colors ${
              days === d ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:bg-accent'
            }`}
          >
            {d}d
          </button>
        ))}
      </div>

      {/* Daily Visits */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Activity className="h-4 w-4" />Daily Visits</CardTitle>
          <CardDescription>Unique visits per day</CardDescription>
        </CardHeader>
        <CardContent>
          {loading
            ? <div className="flex h-64 items-center justify-center text-muted-foreground text-sm">Loading…</div>
            : chartData.length === 0
              ? <div className="flex h-64 items-center justify-center text-muted-foreground text-sm">No data for this period</div>
              : (
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={chartData} margin={{ top: 4, right: 16, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                    <XAxis
                      dataKey="date"
                      tick={{ fontSize: 11 }}
                      tickFormatter={formatLabel}
                      interval={tickInterval}
                    />
                    <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                    <Tooltip
                      labelFormatter={formatLabel}
                      contentStyle={tooltipStyle}
                    />
                    <Bar dataKey="visits" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} name="Visits" />
                  </BarChart>
                </ResponsiveContainer>
              )
          }
        </CardContent>
      </Card>

      {/* Daily Duration */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Clock className="h-4 w-4" />Daily Duration</CardTitle>
          <CardDescription>Total minutes people spent per day</CardDescription>
        </CardHeader>
        <CardContent>
          {loading
            ? <div className="flex h-64 items-center justify-center text-muted-foreground text-sm">Loading…</div>
            : chartData.length === 0
              ? <div className="flex h-64 items-center justify-center text-muted-foreground text-sm">No data for this period</div>
              : (
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={chartData} margin={{ top: 4, right: 16, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                    <XAxis
                      dataKey="date"
                      tick={{ fontSize: 11 }}
                      tickFormatter={formatLabel}
                      interval={tickInterval}
                    />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip
                      labelFormatter={formatLabel}
                      contentStyle={tooltipStyle}
                    />
                    <Legend />
                    <Line type="monotone" dataKey="total_minutes" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} name="Minutes" />
                    <Line type="monotone" dataKey="avg_people" stroke="hsl(142, 76%, 36%)" strokeWidth={2} dot={false} name="Avg People" />
                  </LineChart>
                </ResponsiveContainer>
              )
          }
        </CardContent>
      </Card>

      {/* Hourly Breakdown */}
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <CardTitle className="flex items-center gap-2"><Calendar className="h-4 w-4" />Hourly Breakdown</CardTitle>
              <CardDescription>Visit distribution by hour for selected date</CardDescription>
            </div>

            {/* Custom date picker */}
            <div className="relative">
              <button
                onClick={() => setCalendarOpen(o => !o)}
                className={[
                  'flex items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition-colors',
                  calendarOpen
                    ? 'border-primary bg-primary/5'
                    : 'border-input bg-background hover:bg-accent',
                ].join(' ')}
              >
                <Calendar className="h-3.5 w-3.5 text-muted-foreground" />
                {formatLabel(selectedDate)}
                {dotDates.has(selectedDate) && (
                  <span className="h-1.5 w-1.5 rounded-full bg-primary" title="Has data" />
                )}
              </button>

              {calendarOpen && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setCalendarOpen(false)} />
                  <div className="absolute right-0 z-20 mt-2">
                    <MiniCalendar
                      selected={selectedDate}
                      onSelect={d => { setSelectedDate(d); setCalendarOpen(false) }}
                      dotDates={dotDates}
                    />
                  </div>
                </>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {loadingHourly
            ? <div className="flex h-64 items-center justify-center text-muted-foreground text-sm">Loading…</div>
            : (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={hourlyFull} margin={{ top: 4, right: 16, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                  <XAxis
                    dataKey="hour"
                    tickFormatter={(h: number) => `${String(h).padStart(2, '0')}:00`}
                    tick={{ fontSize: 10 }}
                    interval={2}
                  />
                  <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                  <Tooltip
                    labelFormatter={(h: number) => `${String(h).padStart(2, '0')}:00`}
                    contentStyle={tooltipStyle}
                  />
                  <Legend />
                  <Bar dataKey="visits" fill="hsl(217, 91%, 60%)" radius={[4, 4, 0, 0]} name="Visits" />
                  <Bar dataKey="peak_people" fill="hsl(142, 76%, 36%)" radius={[4, 4, 0, 0]} name="Peak People" />
                </BarChart>
              </ResponsiveContainer>
            )
          }
        </CardContent>
      </Card>
    </div>
  )
}
