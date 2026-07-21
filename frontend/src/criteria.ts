import type { RouteWhy } from './api'

export interface CriterionChip {
  label: string
  value: string
  title: string
  penalized: boolean
}

/** The five scoring.yaml criteria, rendered per route option.
 *  The first three are contributions; the last two are gates that can only
 *  subtract — shown as a multiplier when they actually bit. */
export function criteriaChips(why: RouteWhy): CriterionChip[] {
  const pct = (v: number) => `${Math.round(v * 100)}%`
  const times = (v: number) => `×${v.toFixed(2)}`
  return [
    {
      label: 'Corners',
      value: pct(why.curvature),
      title: 'Curvature — how much this route bends (60% of the fun index)',
      penalized: false,
    },
    {
      label: 'Hills',
      value: pct(why.elevation),
      title: 'Elevation relief — rolling terrain (15%)',
      penalized: false,
    },
    {
      label: 'Road type',
      value: pct(why.road_class),
      title: 'Road type — rural backroads beat highways and subdivisions (25%)',
      penalized: false,
    },
    // 0.9 is the "surface untagged" discount, not actual gravel — don't cry wolf.
    why.surface >= 0.9
      ? {
          label: 'Surface',
          value: 'paved',
          title: 'Surface gate — no unpaved sections',
          penalized: false,
        }
      : {
          label: 'Surface',
          value: times(why.surface),
          title: 'Surface gate — unpaved sections heavily penalized (Miata rule)',
          penalized: true,
        },
    why.safety >= 0.995
      ? {
          label: 'Safety',
          value: 'no penalty',
          title:
            'Safety gate — no penalty applied for driveway density or tight curves on low-limit roads',
          penalized: false,
        }
      : {
          label: 'Safety',
          value: times(why.safety),
          title:
            'Safety gate — penalized for dense driveways/junctions or tight curves on low-limit roads',
          penalized: true,
        },
  ]
}
