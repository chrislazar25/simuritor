import { useEffect, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'

type Rect = { x: number; y: number; w: number; h: number }

const MIN_W = 320
const MIN_H = 200
const MARGIN = 16

/** Keep the whole panel inside the viewport, and at least the minimum size where it fits. */
function clamp(r: Rect): Rect {
  const vw = window.innerWidth
  const vh = window.innerHeight
  const w = Math.min(Math.max(r.w, MIN_W), vw)
  const h = Math.min(Math.max(r.h, MIN_H), vh)
  return { w, h, x: Math.min(Math.max(r.x, 0), vw - w), y: Math.min(Math.max(r.y, 0), vh - h) }
}

function load(key: string, initial: Omit<Rect, 'x' | 'y'>): Rect {
  try {
    const saved = JSON.parse(localStorage.getItem(key) ?? 'null') as Partial<Rect> | null
    if (saved && [saved.x, saved.y, saved.w, saved.h].every(Number.isFinite)) return clamp(saved as Rect)
  } catch {
    // Storage blocked or bad JSON: fall through to the default spot.
  }
  return clamp({ ...initial, x: MARGIN, y: window.innerHeight - initial.h - MARGIN })
}

function save(key: string, rect: Rect) {
  try {
    localStorage.setItem(key, JSON.stringify(rect))
  } catch {
    // Storage blocked: the panel just won't remember where it was.
  }
}

/**
 * A glass panel floating over the map (docs/design.md, "The HUD"). Drag it by the header, resize
 * it from the bottom-right corner, double-click the header to expand it; Esc collapses. Position
 * and size persist in localStorage under `storageKey`.
 */
export function FloatingPanel({
  title,
  storageKey,
  initialSize,
  children,
}: {
  title: string
  storageKey: string
  initialSize: { w: number; h: number }
  children: ReactNode
}) {
  const [rect, setRect] = useState(() => load(storageKey, initialSize))
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    const onResize = () => setRect(clamp)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  useEffect(() => {
    if (!expanded) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setExpanded(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])

  // Pointer capture keeps the gesture on this element even when the pointer outruns the panel.
  function startGesture(e: ReactPointerEvent<HTMLElement>, kind: 'move' | 'resize') {
    if (expanded || e.button !== 0) return
    if ((e.target as HTMLElement).closest('button')) return
    const el = e.currentTarget
    const start = { px: e.clientX, py: e.clientY, rect }
    let last = rect
    el.setPointerCapture(e.pointerId)

    const onMove = (ev: PointerEvent) => {
      const dx = ev.clientX - start.px
      const dy = ev.clientY - start.py
      const r = start.rect
      last =
        kind === 'move'
          ? clamp({ ...r, x: r.x + dx, y: r.y + dy })
          : clamp({
              ...r,
              w: Math.min(r.w + dx, window.innerWidth - r.x),
              h: Math.min(r.h + dy, window.innerHeight - r.y),
            })
      setRect(last)
    }
    const onEnd = () => {
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerup', onEnd)
      el.removeEventListener('pointercancel', onEnd)
      save(storageKey, last)
    }
    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerup', onEnd)
    el.addEventListener('pointercancel', onEnd)
  }

  return (
    <section
      className={expanded ? 'floating expanded' : 'floating'}
      style={expanded ? undefined : { left: rect.x, top: rect.y, width: rect.w, height: rect.h }}
      aria-label={title}
    >
      <header
        className="floating-header"
        onPointerDown={(e) => startGesture(e, 'move')}
        onDoubleClick={(e) => {
          if (!(e.target as HTMLElement).closest('button')) setExpanded((x) => !x)
        }}
      >
        <span>{title}</span>
        <button
          type="button"
          aria-label={expanded ? 'Collapse' : 'Expand'}
          title={expanded ? 'Collapse (Esc)' : 'Expand'}
          onClick={() => setExpanded((x) => !x)}
        >
          {expanded ? '⤡' : '⤢'}
        </button>
      </header>
      <div className="floating-body">{children}</div>
      {!expanded && <div className="floating-resize" onPointerDown={(e) => startGesture(e, 'resize')} />}
    </section>
  )
}
