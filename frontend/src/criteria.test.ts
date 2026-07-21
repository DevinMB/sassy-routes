import { describe, expect, it } from 'vitest'
import { criteriaChips } from './criteria'
import type { RouteWhy } from './api'

const clean: RouteWhy = {
  curvature: 0.58,
  elevation: 0.31,
  road_class: 0.82,
  surface: 1.0,
  safety: 1.0,
  scored_fraction: 1.0,
}

describe('criteriaChips', () => {
  it('shows all five scoring criteria', () => {
    expect(criteriaChips(clean).map((c) => c.label)).toEqual([
      'Corners',
      'Hills',
      'Road type',
      'Surface',
      'Safety',
    ])
  })

  it('renders contributions as percentages', () => {
    const [corners, hills, roads] = criteriaChips(clean)
    expect(corners.value).toBe('58%')
    expect(hills.value).toBe('31%')
    expect(roads.value).toBe('82%')
  })

  it('treats an unpenalized route as paved with no safety penalty', () => {
    const chips = criteriaChips(clean)
    expect(chips.every((c) => !c.penalized)).toBe(true)
    expect(chips[3].value).toBe('paved')
    expect(chips[4].value).toBe('no penalty')
  })

  it('does not flag the untagged-surface discount as unpaved', () => {
    // 0.9 is the "no surface tag" discount, not gravel — crying wolf here
    // would make the real unpaved warning meaningless.
    const chips = criteriaChips({ ...clean, surface: 0.9 })
    expect(chips[3].penalized).toBe(false)
    expect(chips[3].value).toBe('paved')
  })

  it('flags real unpaved sections with the multiplier', () => {
    const chips = criteriaChips({ ...clean, surface: 0.51 })
    expect(chips[3].penalized).toBe(true)
    expect(chips[3].value).toBe('×0.51')
  })

  it('flags an applied safety penalty with the multiplier', () => {
    const chips = criteriaChips({ ...clean, safety: 0.5 })
    expect(chips[4].penalized).toBe(true)
    expect(chips[4].value).toBe('×0.50')
  })
})
