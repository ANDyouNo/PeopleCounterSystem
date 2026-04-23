export interface AppState {
  people_now: number
  fps: number
  inference_ms: number
  total_unique: number
  today_visits: number
  today_minutes: number
  max_people_today: number
  showcase_connected: boolean
  light_connected: boolean
  showcase_forced: number[]
  light_forced: boolean
}

export interface SettingItem {
  value: string | number | boolean
  type: 'int' | 'float' | 'bool' | 'string'
  description: string
  category: string
  restart_required: boolean
}

export interface SettingsMap {
  [key: string]: SettingItem
}

export interface DailyStat {
  date: string
  visits: number
  total_minutes: number
  max_people: number
  avg_people: number
}

export interface HourlyStat {
  hour: number
  visits: number
  total_minutes: number
  peak_people: number
}

export interface StatsSummary {
  [key: string]: number | string
}

export interface ExclusionZone {
  name: string
  pt1: [number, number]
  pt2: [number, number]
  enabled: boolean
}

export interface ZonesResponse {
  zones: ExclusionZone[]
}

export interface Effect {
  id: string
  name: string
  description: string
  code: string
  enabled: boolean
  created_at: number
}

export interface EffectsStatus {
  enabled: boolean
  active_id: string | null
  active_name: string | null
  last_error: string | null
}

const BASE = ''

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  }
  return res.json()
}

export const api = {
  getState: () => request<AppState>('/api/state'),

  getSettings: () => request<SettingsMap>('/api/settings'),

  updateSettings: (values: Record<string, string | number | boolean>) =>
    request<{ updated: string[] }>('/api/settings', {
      method: 'PUT',
      body: JSON.stringify(values),
    }),

  showcaseForceOn: (ids: number[] | null) =>
    request<void>('/api/control/showcases/force_on', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),

  showcaseForceOff: (ids: number[] | null) =>
    request<void>('/api/control/showcases/force_off', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),

  lightForceOn: () =>
    request<void>('/api/control/light/force_on', { method: 'POST' }),

  lightForceOff: () =>
    request<void>('/api/control/light/force_off', { method: 'POST' }),

  getDailyStats: (days = 30) =>
    request<DailyStat[]>(`/api/stats/daily?days=${days}`),

  getHourlyStats: (date: string) =>
    request<HourlyStat[]>(`/api/stats/hourly?date=${date}`),

  getStatsSummary: () => request<StatsSummary>('/api/stats/summary'),

  getZones: () => request<ZonesResponse>('/api/zones'),

  saveZones: (zones: ExclusionZone[]) =>
    request<{ saved: number }>('/api/zones', {
      method: 'PUT',
      body: JSON.stringify({ zones }),
    }),

  getSnapshotUrl: () => '/api/zones/snapshot',

  // Effects
  getEffects: () => request<Effect[]>('/api/effects'),

  getEffectsStatus: () => request<EffectsStatus>('/api/effects/status'),

  setEffectsEnabled: (enabled: boolean) =>
    request<EffectsStatus>('/api/effects/enabled', {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    }),

  createEffect: (name: string, code: string, description?: string) =>
    request<Effect>('/api/effects', {
      method: 'POST',
      body: JSON.stringify({ name, code, description: description ?? '' }),
    }),

  updateEffect: (id: string, patch: Partial<Pick<Effect, 'name' | 'code' | 'description' | 'enabled'>>) =>
    request<Effect>(`/api/effects/${id}`, {
      method: 'PUT',
      body: JSON.stringify(patch),
    }),

  deleteEffect: (id: string) =>
    fetch(`/api/effects/${id}`, { method: 'DELETE' }),

  activateEffect: (id: string) =>
    request<EffectsStatus>(`/api/effects/${id}/activate`, { method: 'POST' }),

  deactivateEffect: () =>
    request<{ ok: boolean }>('/api/effects/deactivate', { method: 'POST' }),
}
