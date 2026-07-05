export interface LatLng {
  lat: number
  lng: number
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
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail = body && typeof body.detail === 'string' ? body.detail : null
    throw new Error(detail ?? `search failed (${res.status})`)
  }
  const body = await res.json()
  return body.results
}

export async function fetchRoute(origin: LatLng, destination: LatLng): Promise<RouteResult> {
  const res = await fetch('/api/route', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ origin, destination }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail = body && typeof body.detail === 'string' ? body.detail : null
    throw new Error(detail ?? `route request failed (${res.status})`)
  }
  return res.json()
}
