import { useEffect, useState, useCallback } from 'react'
import { Save, AlertTriangle, RefreshCw } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Switch } from '../components/ui/switch'
import { Badge } from '../components/ui/badge'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../components/ui/tabs'
import { useToast } from '../components/ui/toast'
import { api, type SettingsMap, type SettingItem } from '../api/client'

type LocalValues = Record<string, string | number | boolean>

function SettingRow({
  settingKey,
  setting,
  localValue,
  onChange,
  dirty,
}: {
  settingKey: string
  setting: SettingItem
  localValue: string | number | boolean
  onChange: (key: string, value: string | number | boolean) => void
  dirty: boolean
}) {
  return (
    <div className={`flex flex-col gap-2 rounded-lg border p-4 transition-colors ${dirty ? 'border-primary/50 bg-primary/5' : ''}`}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <label
              htmlFor={settingKey}
              className="text-sm font-medium leading-none cursor-pointer"
            >
              {setting.description}
            </label>
            {setting.restart_required && (
              <Badge variant="warning" className="gap-1">
                <AlertTriangle className="h-3 w-3" />
                Requires restart
              </Badge>
            )}
            {dirty && (
              <Badge variant="secondary" className="text-xs">Modified</Badge>
            )}
          </div>
          <p className="mt-1 text-xs text-muted-foreground font-mono">{settingKey}</p>
        </div>

        <div className="shrink-0">
          {setting.type === 'bool' ? (
            <Switch
              id={settingKey}
              checked={Boolean(localValue)}
              onCheckedChange={checked => onChange(settingKey, checked)}
            />
          ) : setting.type === 'int' ? (
            <Input
              id={settingKey}
              type="number"
              value={String(localValue)}
              onChange={e => onChange(settingKey, parseInt(e.target.value, 10))}
              className="w-32 text-right"
              step={1}
            />
          ) : setting.type === 'float' ? (
            <Input
              id={settingKey}
              type="number"
              value={String(localValue)}
              onChange={e => onChange(settingKey, parseFloat(e.target.value))}
              className="w-32 text-right"
              step={0.01}
            />
          ) : (
            <Input
              id={settingKey}
              type="text"
              value={String(localValue)}
              onChange={e => onChange(settingKey, e.target.value)}
              className="w-48"
            />
          )}
        </div>
      </div>
    </div>
  )
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<SettingsMap>({})
  const [localValues, setLocalValues] = useState<LocalValues>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const { toast } = useToast()

  const loadSettings = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.getSettings()
      setSettings(data)
      const vals: LocalValues = {}
      for (const [k, v] of Object.entries(data)) {
        vals[k] = v.value
      }
      setLocalValues(vals)
    } catch (err) {
      console.error('Failed to load settings', err)
      toast({ title: 'Failed to load settings', variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => {
    loadSettings()
  }, [loadSettings])

  const handleChange = (key: string, value: string | number | boolean) => {
    setLocalValues(prev => ({ ...prev, [key]: value }))
  }

  const getDirtyKeys = (): string[] => {
    return Object.keys(localValues).filter(k => {
      const orig = settings[k]?.value
      return orig !== localValues[k]
    })
  }

  const handleSave = async () => {
    const dirty = getDirtyKeys()
    if (dirty.length === 0) {
      toast({ title: 'No changes to save', variant: 'default' })
      return
    }
    setSaving(true)
    try {
      const payload: LocalValues = {}
      for (const k of dirty) {
        payload[k] = localValues[k]
      }
      const result = await api.updateSettings(payload)
      // Update original values
      setSettings(prev => {
        const next = { ...prev }
        for (const k of result.updated) {
          if (next[k]) {
            next[k] = { ...next[k], value: localValues[k] }
          }
        }
        return next
      })
      const hasRestart = dirty.some(k => settings[k]?.restart_required)
      toast({
        title: 'Settings saved',
        description: hasRestart
          ? `Saved ${result.updated.length} setting(s). Some changes require a restart.`
          : `Saved ${result.updated.length} setting(s) successfully.`,
        variant: 'success',
      })
    } catch (err) {
      console.error('Failed to save settings', err)
      toast({ title: 'Failed to save settings', variant: 'destructive' })
    } finally {
      setSaving(false)
    }
  }

  // Group by category
  const categories = Array.from(
    new Set(Object.values(settings).map(s => s.category))
  ).sort()

  const getSettingsForCategory = (cat: string) =>
    Object.entries(settings).filter(([, v]) => v.category === cat)

  const dirtyKeys = new Set(getDirtyKeys())
  const dirtyCount = dirtyKeys.size
  const hasRestartRequired = [...dirtyKeys].some(k => settings[k]?.restart_required)

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="flex items-center gap-2 text-muted-foreground">
          <RefreshCw className="h-4 w-4 animate-spin" />
          Loading settings...
        </div>
      </div>
    )
  }

  if (categories.length === 0) {
    return (
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-col items-center gap-4 py-8 text-center">
            <p className="text-muted-foreground">No settings available.</p>
            <Button variant="outline" onClick={loadSettings} className="gap-2">
              <RefreshCw className="h-4 w-4" />
              Reload
            </Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold">System Settings</h2>
          <p className="text-sm text-muted-foreground">
            Configure camera, detection, and device settings.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {dirtyCount > 0 && (
            <div className="flex items-center gap-2">
              {hasRestartRequired && (
                <Badge variant="warning" className="gap-1">
                  <AlertTriangle className="h-3 w-3" />
                  Restart required
                </Badge>
              )}
              <Badge variant="secondary">{dirtyCount} change{dirtyCount !== 1 ? 's' : ''}</Badge>
            </div>
          )}
          <Button variant="outline" size="sm" onClick={loadSettings} className="gap-1.5">
            <RefreshCw className="h-3.5 w-3.5" />
            Reload
          </Button>
          <Button
            onClick={handleSave}
            disabled={saving || dirtyCount === 0}
            size="sm"
            className="gap-1.5"
          >
            <Save className="h-3.5 w-3.5" />
            {saving ? 'Saving...' : 'Save Changes'}
          </Button>
        </div>
      </div>

      {/* Tabs by category */}
      <Tabs defaultValue={categories[0]}>
        <TabsList className="flex-wrap h-auto gap-1">
          {categories.map(cat => {
            const catSettings = getSettingsForCategory(cat)
            const catDirty = catSettings.filter(([k]) => dirtyKeys.has(k)).length
            return (
              <TabsTrigger key={cat} value={cat} className="gap-1.5 capitalize">
                {cat}
                {catDirty > 0 && (
                  <span className="rounded-full bg-primary px-1.5 py-0.5 text-[10px] text-primary-foreground leading-none">
                    {catDirty}
                  </span>
                )}
              </TabsTrigger>
            )
          })}
        </TabsList>

        {categories.map(cat => {
          const catSettings = getSettingsForCategory(cat)
          return (
            <TabsContent key={cat} value={cat}>
              <Card>
                <CardHeader>
                  <CardTitle className="capitalize">{cat} Settings</CardTitle>
                  <CardDescription>
                    {catSettings.length} setting{catSettings.length !== 1 ? 's' : ''}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="space-y-3">
                    {catSettings.map(([key, setting]) => (
                      <SettingRow
                        key={key}
                        settingKey={key}
                        setting={setting}
                        localValue={localValues[key] ?? setting.value}
                        onChange={handleChange}
                        dirty={dirtyKeys.has(key)}
                      />
                    ))}
                  </div>
                </CardContent>
              </Card>
            </TabsContent>
          )
        })}
      </Tabs>

      {/* Save bar at bottom when there are changes */}
      {dirtyCount > 0 && (
        <div className="sticky bottom-0 rounded-lg border bg-card/95 backdrop-blur p-4 shadow-lg">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-2">
              {hasRestartRequired && (
                <AlertTriangle className="h-4 w-4 text-yellow-500" />
              )}
              <p className="text-sm">
                <span className="font-medium">{dirtyCount} unsaved change{dirtyCount !== 1 ? 's' : ''}</span>
                {hasRestartRequired && (
                  <span className="ml-1 text-muted-foreground">— some settings require a restart</span>
                )}
              </p>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={loadSettings}
              >
                Discard
              </Button>
              <Button
                size="sm"
                onClick={handleSave}
                disabled={saving}
                className="gap-1.5"
              >
                <Save className="h-3.5 w-3.5" />
                {saving ? 'Saving...' : 'Save Changes'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
