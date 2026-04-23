import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Play, Square, Trash2, Plus, Download, ChevronDown, ChevronUp, AlertTriangle, Sparkles } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { useToast } from '../components/ui/toast'
import { api, type Effect, type EffectsStatus } from '../api/client'
import { cn } from '../lib/utils'

// ── Types ──────────────────────────────────────────────────────

type ViewMode = 'collapsed' | 'expanded'

// ── Default code template for new effects ─────────────────────

const NEW_EFFECT_TEMPLATE = `import math

def tick(t, ctx):
    """
    t   — seconds since effect started (float)
    ctx.channel_count — number of showcases (int)
    ctx.people        — people in frame right now (int)

    Return a list of brightness values, one per showcase.
    Each value: 0.0 (off) … 1.0 (full brightness)
    """
    period = 3.0  # seconds per breath
    v = 0.70 + 0.30 * (math.sin(t * 2 * math.pi / period) * 0.5 + 0.5)
    return [v] * ctx.channel_count
`

// ── Toggle switch ──────────────────────────────────────────────

function Toggle({
  checked,
  onChange,
  disabled = false,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
}) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-7 w-12 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary',
        checked ? 'bg-primary' : 'bg-input',
        disabled && 'opacity-50 cursor-not-allowed',
      )}
    >
      <span
        className={cn(
          'pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-md transition-transform',
          checked ? 'translate-x-5' : 'translate-x-0',
        )}
      />
    </button>
  )
}

// ── Effect card ────────────────────────────────────────────────

interface EffectCardProps {
  effect: Effect
  isActive: boolean
  engineEnabled: boolean
  onActivate: (id: string) => void
  onDeactivate: () => void
  onUpdate: (id: string, patch: Partial<Effect>) => Promise<void>
  onDelete: (id: string) => void
}

function EffectCard({
  effect,
  isActive,
  engineEnabled,
  onActivate,
  onDeactivate,
  onUpdate,
  onDelete,
}: EffectCardProps) {
  const [view, setView]       = useState<ViewMode>('collapsed')
  const [editName, setEditName] = useState(effect.name)
  const [editDesc, setEditDesc] = useState(effect.description)
  const [editCode, setEditCode] = useState(effect.code)
  const [saving, setSaving]   = useState(false)
  const [dirty, setDirty]     = useState(false)
  const codeRef = useRef<HTMLTextAreaElement>(null)

  // Sync when effect changes externally
  useEffect(() => {
    setEditName(effect.name)
    setEditDesc(effect.description)
    setEditCode(effect.code)
    setDirty(false)
  }, [effect.name, effect.description, effect.code])

  const handleCodeChange = (v: string) => {
    setEditCode(v)
    setDirty(v !== effect.code || editName !== effect.name || editDesc !== effect.description)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await onUpdate(effect.id, { name: editName, description: editDesc, code: editCode })
      setDirty(false)
    } finally {
      setSaving(false)
    }
  }

  // Tab key inserts 4 spaces in the code editor
  const handleTabKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Tab') {
      e.preventDefault()
      const el = e.currentTarget
      const start = el.selectionStart
      const end   = el.selectionEnd
      const spaces = '    '
      const next = editCode.substring(0, start) + spaces + editCode.substring(end)
      setEditCode(next)
      setDirty(true)
      // Restore cursor position after React re-render
      requestAnimationFrame(() => {
        el.selectionStart = start + spaces.length
        el.selectionEnd   = start + spaces.length
      })
    }
  }

  const expanded = view === 'expanded'

  return (
    <Card className={cn(
      'transition-all',
      isActive && engineEnabled && 'border-primary shadow-[0_0_0_1px_hsl(var(--primary))]',
    )}>
      {/* Header row */}
      <CardHeader className="pb-2 pt-4 px-4">
        <div className="flex items-center gap-3">
          {/* Active indicator */}
          <div className={cn(
            'h-2.5 w-2.5 shrink-0 rounded-full transition-colors',
            isActive && engineEnabled
              ? 'bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.6)]'
              : 'bg-muted-foreground/20',
          )} />

          {/* Name (editable when expanded) */}
          {expanded ? (
            <input
              className="flex-1 bg-transparent text-sm font-semibold outline-none border-b border-transparent focus:border-primary transition-colors"
              value={editName}
              onChange={e => { setEditName(e.target.value); setDirty(true) }}
            />
          ) : (
            <CardTitle className="flex-1 text-sm font-semibold">{effect.name}</CardTitle>
          )}

          {/* Badges */}
          {isActive && engineEnabled && (
            <Badge variant="default" className="text-xs shrink-0">Running</Badge>
          )}

          {/* Action buttons */}
          <div className="flex items-center gap-1 shrink-0">
            {isActive && engineEnabled ? (
              <button
                onClick={onDeactivate}
                title="Stop effect"
                className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors"
              >
                <Square className="h-3.5 w-3.5" />
              </button>
            ) : (
              <button
                onClick={() => onActivate(effect.id)}
                title="Activate effect"
                className="rounded p-1.5 text-muted-foreground hover:bg-primary/10 hover:text-primary transition-colors"
              >
                <Play className="h-3.5 w-3.5" />
              </button>
            )}
            <button
              onClick={() => onDelete(effect.id)}
              title="Delete effect"
              className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={() => setView(v => v === 'collapsed' ? 'expanded' : 'collapsed')}
              title={expanded ? 'Collapse' : 'Edit code'}
              className="rounded p-1.5 text-muted-foreground hover:bg-accent transition-colors"
            >
              {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </button>
          </div>
        </div>

        {/* Description (always visible when not expanded) */}
        {!expanded && effect.description && (
          <p className="mt-1 ml-[calc(0.625rem+0.75rem)] text-xs text-muted-foreground">
            {effect.description}
          </p>
        )}
      </CardHeader>

      {/* Expanded: description + code editor */}
      {expanded && (
        <CardContent className="pt-0 px-4 pb-4 space-y-3">
          <input
            className="w-full bg-transparent text-xs text-muted-foreground outline-none border-b border-transparent focus:border-border transition-colors"
            placeholder="Short description (optional)"
            value={editDesc}
            onChange={e => { setEditDesc(e.target.value); setDirty(true) }}
          />

          {/* Code editor */}
          <div className="rounded-md border bg-[hsl(var(--card))] overflow-hidden">
            <div className="flex items-center justify-between px-3 py-1.5 border-b bg-muted/40">
              <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
                Python · tick(t, ctx)
              </span>
              {dirty && (
                <span className="text-[10px] text-yellow-600 dark:text-yellow-400">● unsaved</span>
              )}
            </div>
            <textarea
              ref={codeRef}
              value={editCode}
              onChange={e => handleCodeChange(e.target.value)}
              onKeyDown={handleTabKey}
              spellCheck={false}
              className={cn(
                'w-full min-h-[220px] resize-y bg-transparent p-3',
                'font-mono text-xs leading-relaxed text-foreground',
                'outline-none focus:outline-none',
                'placeholder:text-muted-foreground',
              )}
              style={{ tabSize: 4 }}
            />
          </div>

          {/* Save button */}
          <div className="flex justify-end">
            <button
              onClick={handleSave}
              disabled={!dirty || saving}
              className={cn(
                'rounded-md px-4 py-1.5 text-xs font-medium transition-colors',
                dirty
                  ? 'bg-primary text-primary-foreground hover:bg-primary/90'
                  : 'bg-muted text-muted-foreground cursor-not-allowed',
              )}
            >
              {saving ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        </CardContent>
      )}
    </Card>
  )
}

// ── Main page ──────────────────────────────────────────────────

export default function EffectsPage() {
  const { toast } = useToast()

  const [status, setStatus]   = useState<EffectsStatus>({
    enabled: false, active_id: null, active_name: null, last_error: null,
  })
  const [effects, setEffects] = useState<Effect[]>([])
  const [loading, setLoading] = useState(true)
  const [togglingEngine, setTogglingEngine] = useState(false)
  const [showNewForm, setShowNewForm] = useState(false)
  const [newName, setNewName] = useState('')

  // ── Load ──

  const load = useCallback(async () => {
    try {
      const [eff, st] = await Promise.all([api.getEffects(), api.getEffectsStatus()])
      setEffects(eff)
      setStatus(st)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // Poll status every 2s to catch runtime errors
  useEffect(() => {
    const id = setInterval(async () => {
      try {
        setStatus(await api.getEffectsStatus())
      } catch { /* ignore */ }
    }, 2000)
    return () => clearInterval(id)
  }, [])

  // ── Handlers ──

  const handleToggleEngine = async (enabled: boolean) => {
    setTogglingEngine(true)
    try {
      const st = await api.setEffectsEnabled(enabled)
      setStatus(st)
    } catch {
      toast({ title: 'Failed to toggle effects', variant: 'destructive' })
    } finally {
      setTogglingEngine(false)
    }
  }

  const handleActivate = async (id: string) => {
    try {
      const st = await api.activateEffect(id)
      setStatus(st)
      if (st.last_error) {
        toast({ title: 'Script error', description: st.last_error, variant: 'destructive' })
      } else {
        toast({ title: `Effect activated` })
      }
    } catch (e: any) {
      toast({ title: 'Activation failed', description: e.message, variant: 'destructive' })
    }
  }

  const handleDeactivate = async () => {
    try {
      await api.deactivateEffect()
      setStatus(prev => ({ ...prev, active_id: null, active_name: null }))
    } catch {
      toast({ title: 'Failed to stop effect', variant: 'destructive' })
    }
  }

  const handleUpdate = async (id: string, patch: Partial<Effect>) => {
    try {
      const updated = await api.updateEffect(id, patch)
      setEffects(prev => prev.map(e => e.id === id ? updated : e))
      toast({ title: 'Effect saved' })
    } catch {
      toast({ title: 'Save failed', variant: 'destructive' })
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this effect?')) return
    try {
      if (status.active_id === id) {
        await api.deactivateEffect()
      }
      await api.deleteEffect(id)
      setEffects(prev => prev.filter(e => e.id !== id))
      if (status.active_id === id) {
        setStatus(prev => ({ ...prev, active_id: null, active_name: null }))
      }
      toast({ title: 'Effect deleted' })
    } catch {
      toast({ title: 'Delete failed', variant: 'destructive' })
    }
  }

  const handleCreate = async () => {
    const name = newName.trim() || 'New Effect'
    try {
      const effect = await api.createEffect(name, NEW_EFFECT_TEMPLATE, '')
      setEffects(prev => [...prev, effect])
      setShowNewForm(false)
      setNewName('')
      toast({ title: `Created: ${effect.name}` })
    } catch {
      toast({ title: 'Create failed', variant: 'destructive' })
    }
  }

  const handleDownloadDocs = () => {
    window.open('/docs/effects_scripting.md', '_blank')
  }

  // ── Render ──

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            Showcase Effects
          </h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Python-scripted lighting effects for display showcases
          </p>
        </div>
        <button
          onClick={handleDownloadDocs}
          className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-accent transition-colors"
          title="Download scripting documentation"
        >
          <Download className="h-3.5 w-3.5" />
          API Docs
        </button>
      </div>

      {/* Engine toggle card */}
      <Card>
        <CardContent className="pt-5 pb-5">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold">Effects Engine</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                {status.enabled
                  ? status.active_id
                    ? `Running: ${status.active_name}`
                    : 'Enabled — no effect selected'
                  : 'Disabled — showcases follow auto/manual mode'}
              </p>
            </div>
            <Toggle
              checked={status.enabled}
              onChange={handleToggleEngine}
              disabled={togglingEngine || loading}
            />
          </div>

          {/* Runtime error banner */}
          {status.last_error && (
            <div className="mt-4 flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2.5">
              <AlertTriangle className="h-4 w-4 text-destructive shrink-0 mt-0.5" />
              <div className="min-w-0">
                <p className="text-xs font-medium text-destructive">Script runtime error</p>
                <pre className="mt-1 text-[10px] text-destructive/80 whitespace-pre-wrap break-all font-mono leading-relaxed">
                  {status.last_error}
                </pre>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Effects list */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
            Effects ({effects.length})
          </h2>
          <button
            onClick={() => setShowNewForm(v => !v)}
            className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            <Plus className="h-3.5 w-3.5" />
            New Effect
          </button>
        </div>

        {/* New effect quick-form */}
        {showNewForm && (
          <Card className="border-dashed border-primary/40">
            <CardContent className="pt-4 pb-4">
              <div className="flex gap-2">
                <input
                  autoFocus
                  placeholder="Effect name…"
                  value={newName}
                  onChange={e => setNewName(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleCreate()}
                  className="flex-1 rounded-md border bg-background px-3 py-1.5 text-sm outline-none focus:ring-1 focus:ring-primary"
                />
                <button
                  onClick={handleCreate}
                  className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
                >
                  Create
                </button>
                <button
                  onClick={() => { setShowNewForm(false); setNewName('') }}
                  className="rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-accent transition-colors"
                >
                  Cancel
                </button>
              </div>
            </CardContent>
          </Card>
        )}

        {loading ? (
          <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
            Loading…
          </div>
        ) : effects.length === 0 ? (
          <div className="flex h-32 flex-col items-center justify-center gap-2 rounded-lg border border-dashed text-muted-foreground">
            <Sparkles className="h-8 w-8 opacity-30" />
            <p className="text-sm">No effects yet. Create one to get started.</p>
          </div>
        ) : (
          effects.map(effect => (
            <EffectCard
              key={effect.id}
              effect={effect}
              isActive={status.active_id === effect.id}
              engineEnabled={status.enabled}
              onActivate={handleActivate}
              onDeactivate={handleDeactivate}
              onUpdate={handleUpdate}
              onDelete={handleDelete}
            />
          ))
        )}
      </div>
    </div>
  )
}
