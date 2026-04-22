import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ExclusionZone } from '../api/client'
import { useToast } from '../components/ui/toast'

// ── Types ─────────────────────────────────────────────────────

interface DrawingState {
  active: boolean
  startX: number
  startY: number
  currentX: number
  currentY: number
}

// ── Constants ─────────────────────────────────────────────────

const MIN_SIZE = 15  // pixels — minimum zone size

const COLORS = [
  '#ef4444', '#f97316', '#eab308', '#22c55e',
  '#06b6d4', '#6366f1', '#a855f7', '#ec4899',
]

// ── Component ─────────────────────────────────────────────────

export default function ZonesPage() {
  const { toast } = useToast()

  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const imgRef = useRef<HTMLImageElement | null>(null)

  const [zones, setZones] = useState<ExclusionZone[]>([])
  const [drawing, setDrawing] = useState<DrawingState>({
    active: false, startX: 0, startY: 0, currentX: 0, currentY: 0,
  })
  const [saving, setSaving] = useState(false)
  const [imgLoaded, setImgLoaded] = useState(false)
  const [imgError, setImgError] = useState(false)
  const [scale, setScale] = useState({ x: 1, y: 1 })

  // ── Snapshot loading ────────────────────────────────────────

  const loadSnapshot = useCallback(() => {
    setImgLoaded(false)
    setImgError(false)
    const img = new Image()
    // Add cache-buster so clicking Refresh always gets a new frame
    img.src = `${api.getSnapshotUrl()}?t=${Date.now()}`
    img.onload = () => {
      imgRef.current = img
      setImgLoaded(true)
    }
    img.onerror = () => {
      setImgError(true)
      setImgLoaded(true)
    }
  }, [])

  // ── Load zones + initial snapshot ──────────────────────────

  useEffect(() => {
    api.getZones().then(r => setZones(r.zones)).catch(() => {})
    loadSnapshot()
  }, [loadSnapshot])

  // ── Canvas sizing ───────────────────────────────────────────

  useEffect(() => {
    if (!imgLoaded || !canvasRef.current || !containerRef.current) return

    const img = imgRef.current
    const container = containerRef.current
    const maxW = container.clientWidth
    const maxH = Math.max(300, window.innerHeight - 320)

    let drawW = img ? img.naturalWidth : 640
    let drawH = img ? img.naturalHeight : 480

    const ratio = Math.min(maxW / drawW, maxH / drawH, 1)
    drawW = Math.floor(drawW * ratio)
    drawH = Math.floor(drawH * ratio)

    canvasRef.current.width  = drawW
    canvasRef.current.height = drawH

    setScale({
      x: img ? img.naturalWidth / drawW : 1,
      y: img ? img.naturalHeight / drawH : 1,
    })
  }, [imgLoaded])

  // ── Redraw ──────────────────────────────────────────────────

  const redraw = useCallback((overrideDrawing?: DrawingState) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.clearRect(0, 0, canvas.width, canvas.height)

    // Background image or placeholder
    if (imgRef.current && !imgError) {
      ctx.drawImage(imgRef.current, 0, 0, canvas.width, canvas.height)
    } else {
      ctx.fillStyle = '#1f1f2e'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.fillStyle = '#666'
      ctx.font = '16px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText('Camera unavailable', canvas.width / 2, canvas.height / 2)
      ctx.textAlign = 'left'
    }

    // Draw saved zones
    zones.forEach((z, i) => {
      const x1 = z.pt1[0] / scale.x
      const y1 = z.pt1[1] / scale.y
      const x2 = z.pt2[0] / scale.x
      const y2 = z.pt2[1] / scale.y
      const color = COLORS[i % COLORS.length]

      ctx.save()
      ctx.globalAlpha = z.enabled ? 0.35 : 0.15
      ctx.fillStyle = color
      ctx.fillRect(x1, y1, x2 - x1, y2 - y1)
      ctx.restore()

      ctx.strokeStyle = color
      ctx.lineWidth = z.enabled ? 2 : 1
      ctx.setLineDash(z.enabled ? [] : [6, 3])
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
      ctx.setLineDash([])

      // Label
      ctx.font = '12px sans-serif'
      ctx.fillStyle = '#fff'
      ctx.shadowColor = '#000'
      ctx.shadowBlur = 3
      ctx.fillText(z.name, x1 + 4, y1 + 16)
      ctx.shadowBlur = 0
    })

    // Draw in-progress rectangle
    const d = overrideDrawing ?? drawing
    if (d.active) {
      const rx = Math.min(d.startX, d.currentX)
      const ry = Math.min(d.startY, d.currentY)
      const rw = Math.abs(d.currentX - d.startX)
      const rh = Math.abs(d.currentY - d.startY)
      ctx.strokeStyle = '#fff'
      ctx.lineWidth = 2
      ctx.setLineDash([5, 3])
      ctx.strokeRect(rx, ry, rw, rh)
      ctx.setLineDash([])
      ctx.globalAlpha = 0.2
      ctx.fillStyle = '#fff'
      ctx.fillRect(rx, ry, rw, rh)
      ctx.globalAlpha = 1
    }
  }, [zones, drawing, scale, imgError])

  useEffect(() => { redraw() }, [redraw])

  // ── Mouse handlers ──────────────────────────────────────────

  const canvasCoords = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current!.getBoundingClientRect()
    return {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    }
  }

  const onMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const { x, y } = canvasCoords(e)
    setDrawing({ active: true, startX: x, startY: y, currentX: x, currentY: y })
  }

  const onMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!drawing.active) return
    const { x, y } = canvasCoords(e)
    const next = { ...drawing, currentX: x, currentY: y }
    setDrawing(next)
    redraw(next)
  }

  const onMouseUp = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!drawing.active) return
    const { x, y } = canvasCoords(e)

    const x1Canvas = Math.min(drawing.startX, x)
    const y1Canvas = Math.min(drawing.startY, y)
    const x2Canvas = Math.max(drawing.startX, x)
    const y2Canvas = Math.max(drawing.startY, y)

    const stopped: DrawingState = { active: false, startX: 0, startY: 0, currentX: 0, currentY: 0 }
    setDrawing(stopped)

    // Filter tiny zones
    if ((x2Canvas - x1Canvas) < MIN_SIZE || (y2Canvas - y1Canvas) < MIN_SIZE) return

    // Convert canvas px → image px
    const newZone: ExclusionZone = {
      name: `Zone_${zones.length + 1}`,
      pt1: [Math.round(x1Canvas * scale.x), Math.round(y1Canvas * scale.y)],
      pt2: [Math.round(x2Canvas * scale.x), Math.round(y2Canvas * scale.y)],
      enabled: true,
    }
    setZones(prev => [...prev, newZone])
  }

  // Cancel drawing on right-click / escape
  const onContextMenu = (e: React.MouseEvent) => {
    e.preventDefault()
    setDrawing({ active: false, startX: 0, startY: 0, currentX: 0, currentY: 0 })
  }

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setDrawing({ active: false, startX: 0, startY: 0, currentX: 0, currentY: 0 })
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  // ── Zone controls ────────────────────────────────────────────

  const toggleZone = (i: number) => {
    setZones(prev => prev.map((z, idx) =>
      idx === i ? { ...z, enabled: !z.enabled } : z
    ))
  }

  const deleteZone = (i: number) => {
    setZones(prev => {
      const next = prev.filter((_, idx) => idx !== i)
      // Rename remaining so numbers stay sequential
      return next.map((z, idx) => ({ ...z, name: `Zone_${idx + 1}` }))
    })
  }

  const clearAll = () => setZones([])

  // ── Save ─────────────────────────────────────────────────────

  const handleSave = async () => {
    setSaving(true)
    try {
      const res = await api.saveZones(zones)
      toast({ title: `Saved ${res.saved} zone${res.saved !== 1 ? 's' : ''}`, variant: 'default' })
    } catch {
      toast({ title: 'Save failed', variant: 'destructive' })
    } finally {
      setSaving(false)
    }
  }

  // ── Render ───────────────────────────────────────────────────

  return (
    <div className="flex flex-col gap-6 p-6 h-full">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Exclusion Zones</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Draw rectangles over areas where people should not be counted (windows, mirrors, etc.)
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={loadSnapshot}
            className="rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-accent transition-colors"
          >
            ↺ Refresh frame
          </button>
          <button
            onClick={clearAll}
            disabled={zones.length === 0}
            className="rounded-md border border-destructive/50 px-3 py-1.5 text-sm font-medium text-destructive hover:bg-destructive/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Clear all
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-60"
          >
            {saving ? 'Saving…' : 'Save zones'}
          </button>
        </div>
      </div>

      <div className="flex gap-6 flex-1 min-h-0">
        {/* Canvas area */}
        <div className="flex-1 min-w-0 flex flex-col gap-2">
          <div
            ref={containerRef}
            className="relative rounded-lg overflow-hidden border bg-black flex items-center justify-center"
            style={{ minHeight: 300 }}
          >
            {!imgLoaded && (
              <div className="absolute inset-0 flex items-center justify-center text-muted-foreground text-sm">
                Loading frame…
              </div>
            )}
            <canvas
              ref={canvasRef}
              className="block cursor-crosshair"
              style={{ display: imgLoaded ? 'block' : 'none' }}
              onMouseDown={onMouseDown}
              onMouseMove={onMouseMove}
              onMouseUp={onMouseUp}
              onMouseLeave={() => {
                if (drawing.active) {
                  setDrawing({ active: false, startX: 0, startY: 0, currentX: 0, currentY: 0 })
                }
              }}
              onContextMenu={onContextMenu}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            Click and drag to draw a zone. Right-click or Esc to cancel.
          </p>
        </div>

        {/* Zones list */}
        <div className="w-56 shrink-0 flex flex-col gap-2">
          <p className="text-sm font-medium">
            Zones <span className="text-muted-foreground">({zones.length})</span>
          </p>

          {zones.length === 0 ? (
            <div className="flex flex-1 items-center justify-center rounded-lg border border-dashed text-center p-4">
              <p className="text-sm text-muted-foreground">No zones.<br />Draw one on the frame.</p>
            </div>
          ) : (
            <div className="flex flex-col gap-1.5 overflow-y-auto">
              {zones.map((z, i) => (
                <div
                  key={i}
                  className="flex items-center gap-2 rounded-md border px-2.5 py-2 text-sm"
                >
                  {/* Color dot */}
                  <span
                    className="h-3 w-3 rounded-full shrink-0"
                    style={{ background: COLORS[i % COLORS.length] }}
                  />

                  {/* Name */}
                  <span className={`flex-1 truncate ${z.enabled ? '' : 'line-through text-muted-foreground'}`}>
                    {z.name}
                  </span>

                  {/* Toggle enabled */}
                  <button
                    onClick={() => toggleZone(i)}
                    className="text-muted-foreground hover:text-foreground transition-colors text-xs"
                    title={z.enabled ? 'Disable zone' : 'Enable zone'}
                  >
                    {z.enabled ? '●' : '○'}
                  </button>

                  {/* Delete */}
                  <button
                    onClick={() => deleteZone(i)}
                    className="text-muted-foreground hover:text-destructive transition-colors"
                    title="Delete zone"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
