export interface LatLng {
  lat: number
  lng: number
}

export interface Handoff {
  maps_url: string
  waypoints_used: number
  /** worst remaining shortcut-able detour length between two waypoints */
  worst_gap_excess_m: number
  /** false ⇒ waypoint budget couldn't pin the route; warn + offer GPX */
  pinned: boolean
  verified: boolean
}

/** The five scoring criteria behind a route's fun index, length-weighted.
 *  curvature/elevation/road_class are contributions (higher = more fun);
 *  surface/safety are gates (1.0 = no penalty applied). */
export interface RouteWhy {
  curvature: number
  elevation: number
  road_class: number
  surface: number
  safety: number
  scored_fraction: number
}

/** A standout road the route was deliberately sent through (peak-seeking). */
export interface SoughtRoad {
  name: string | null
  fun_index: number
  length_m: number
}

export interface RouteCandidate {
  /** Fun dial λ ∈ [0,1] (0 = fastest) */
  fun_dial: number
  distance_m: number
  time_s: number
  /** Time cost vs. the fastest route, seconds */
  dtime_s: number
  /** Length-weighted fun index [0,1]; null when segment scores unavailable */
  fun_index: number | null
  /** GeoJSON order: [lng, lat] pairs */
  coordinates: [number, number][]
  handoff: Handoff
  /** null when segment scores are unavailable (same condition as fun_index) */
  why: RouteWhy | null
  /** set when this candidate was routed through a specific standout road */
  sought: SoughtRoad | null
}

export interface RouteResult {
  /** candidates[0] is always the fastest route */
  candidates: RouteCandidate[]
}

export interface GeocodeResult {
  label: string
  lat: number
  lng: number
  type?: string | null
}

export async function geocode(query: string): Promise<GeocodeResult[]> {
  const res = await fetch(`/api/geocode?q=${encodeURIComponent(query)}`)
  if (!res.ok) throw new Error(await errorMessage(res, 'search'))
  const body = await res.json()
  return body.results
}

export interface DriveResult {
  distance_m: number
  time_s: number
  fun_index: number | null
  coordinates: [number, number][]
  handoff: Handoff
  why: RouteWhy | null
}

export async function fetchDrive(origin: LatLng, duration_min: number): Promise<DriveResult> {
  const res = await fetch('/api/drive', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ origin, duration_min }),
  })
  if (!res.ok) throw new Error(await errorMessage(res, 'drive'))
  return res.json()
}

export interface ClientEvent {
  type: 'maps_opened'
  fun_dial?: number
  fun_index?: number | null
  dtime_s?: number
}

/** Fire-and-forget analytics — must never affect the UX. */
export function postEvent(event: ClientEvent): void {
  fetch('/api/events', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(event),
  }).catch(() => {})
}

export async function fetchRoute(origin: LatLng, destination: LatLng): Promise<RouteResult> {
  const res = await fetch('/api/route', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ origin, destination }),
  })
  if (!res.ok) throw new Error(await errorMessage(res, 'route'))
  return res.json()
}

/** Prefer the backend's own explanation; fall back to something a human can
 *  act on. 502/503 usually means the routing engine or API is restarting —
 *  a bare "failed (502)" leaves the user with nowhere to go. */
async function errorMessage(res: Response, what: string): Promise<string> {
  const body = await res.json().catch(() => null)
  const detail = body && typeof body.detail === 'string' ? body.detail : null
  if (detail) return detail
  if (res.status === 502 || res.status === 503 || res.status === 504) {
    return 'The routing service is starting up or restarting — try again in a minute.'
  }
  return `${what} request failed (${res.status})`
}
