import { useCallback, useEffect, useRef, useState } from 'react'

/** Height of the strip left on screen when the sheet is dragged down.
 *  Must match --peek in index.css. */
export const PEEK_PX = 92

/** How far you must drag before it counts as a deliberate open/close rather
 *  than a wobble while scrolling. */
export const SNAP_THRESHOLD_PX = 48

export const MOBILE_QUERY = '(max-width: 640px)'

/** Where the sheet should end up after a drag of `dy` from `collapsed`. */
export function snapTo(collapsed: boolean, dy: number, threshold = SNAP_THRESHOLD_PX): boolean {
  if (dy > threshold) return true // dragged down far enough → collapse
  if (dy < -threshold) return false // dragged up far enough → expand
  return collapsed // not decisive: stay put
}

/** Clamp a drag so the sheet can't be pulled above its top or below the peek. */
export function clampDrag(dy: number, collapsed: boolean, travel: number): number {
  const base = collapsed ? travel : 0
  return Math.max(0, Math.min(travel, base + dy)) - base
}

/**
 * Drag-to-collapse behaviour for the mobile bottom sheet.
 *
 * The sheet stays a plain document-flow panel on desktop; this only engages
 * under MOBILE_QUERY, where the panel would otherwise cover the map you just
 * asked it to draw a route on.
 */
export function useSheet() {
  const panelRef = useRef<HTMLDivElement>(null)
  const [collapsed, setCollapsed] = useState(false)
  const [drag, setDrag] = useState<number | null>(null)
  const start = useRef(0)
  const travel = useRef(0)

  const isMobile = () =>
    typeof window !== 'undefined' && window.matchMedia(MOBILE_QUERY).matches

  // A sheet collapsed on a phone must not stay collapsed if the window grows
  // into desktop layout, where the class would just hide the panel.
  useEffect(() => {
    if (typeof window === 'undefined') return
    const mq = window.matchMedia(MOBILE_QUERY)
    const onChange = () => {
      if (!mq.matches) setCollapsed(false)
    }
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (!isMobile()) return
      const el = panelRef.current
      if (!el) return
      travel.current = Math.max(el.offsetHeight - PEEK_PX, 0)
      start.current = e.clientY
      setDrag(0)
      e.currentTarget.setPointerCapture(e.pointerId)
    },
    [],
  )

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (drag === null) return
      setDrag(clampDrag(e.clientY - start.current, collapsed, travel.current))
    },
    [drag, collapsed],
  )

  const onPointerUp = useCallback(
    (e: React.PointerEvent) => {
      if (drag === null) return
      setCollapsed(snapTo(collapsed, drag))
      setDrag(null)
      if (e.currentTarget.hasPointerCapture(e.pointerId)) {
        e.currentTarget.releasePointerCapture(e.pointerId)
      }
    },
    [drag, collapsed],
  )

  /** A tap (no meaningful movement) toggles — dragging a sheet with your thumb
   *  is nice, but tapping the handle is what people try first. */
  const toggle = useCallback(() => {
    if (isMobile()) setCollapsed((c) => !c)
  }, [])

  const expand = useCallback(() => setCollapsed(false), [])

  // While dragging we drive transform directly so it tracks the finger; the
  // rest of the time CSS classes own it, so the snap animates.
  const style =
    drag !== null
      ? {
          transform: `translateY(${(collapsed ? travel.current : 0) + drag}px)`,
          transition: 'none' as const,
        }
      : undefined

  return {
    panelRef,
    collapsed,
    dragging: drag !== null,
    style,
    handleProps: { onPointerDown, onPointerMove, onPointerUp, onPointerCancel: onPointerUp },
    toggle,
    expand,
  }
}
