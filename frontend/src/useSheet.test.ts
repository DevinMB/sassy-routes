import { describe, expect, it } from 'vitest'
import { clampDrag, snapTo, SNAP_THRESHOLD_PX } from './useSheet'

describe('snapTo', () => {
  it('collapses when dragged down decisively', () => {
    expect(snapTo(false, SNAP_THRESHOLD_PX + 10)).toBe(true)
  })

  it('expands when dragged up decisively', () => {
    expect(snapTo(true, -(SNAP_THRESHOLD_PX + 10))).toBe(false)
  })

  it('stays put on a small wobble', () => {
    // a nudge while scrolling the sheet must not flip it
    expect(snapTo(false, 8)).toBe(false)
    expect(snapTo(true, -8)).toBe(true)
  })

  it('does not collapse an already-collapsed sheet dragged further down', () => {
    expect(snapTo(true, 200)).toBe(true)
  })
})

describe('clampDrag', () => {
  const travel = 400

  it('cannot be pulled above the top when expanded', () => {
    expect(clampDrag(-150, false, travel)).toBe(0)
  })

  it('cannot be pushed past the peek when expanded', () => {
    expect(clampDrag(999, false, travel)).toBe(travel)
  })

  it('tracks the finger in between', () => {
    expect(clampDrag(120, false, travel)).toBe(120)
  })

  it('is relative to the collapsed resting position', () => {
    // starting collapsed, dragging up 100px moves 100px up from the bottom stop
    expect(clampDrag(-100, true, travel)).toBe(-100)
    // and cannot go further down than it already is
    expect(clampDrag(50, true, travel)).toBe(0)
  })

  it('handles a sheet with no room to travel', () => {
    expect(clampDrag(50, false, 0)).toBe(0)
  })
})
