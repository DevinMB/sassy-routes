import { useEffect, useRef, useState } from 'react'
import {
  fetchDrive,
  fetchRoute,
  postEvent,
  type GeocodeResult,
  type LatLng,
  type RouteCandidate,
} from './api'
import { criteriaChips } from './criteria'
import { downloadGpx } from './gpx'
import MapView, { type RouteLine } from './MapView'
import SearchBox from './SearchBox'
import { useSheet } from './useSheet'

interface Place extends LatLng {
  label: string
}

// Deliberately about *road quality*, never about speed (guardrail 4).
const DIAL_LABELS: [number, string][] = [
  [0.0, 'Straight there'],
  [0.3, 'Slight detour'],
  [0.6, 'Good roads'],
  [0.9, 'Best roads'],
]

export default function App() {
  const [origin, setOrigin] = useState<Place | null>(null)
  const [destination, setDestination] = useState<Place | null>(null)
  const [candidates, setCandidates] = useState<RouteCandidate[] | null>(null)
  const [selected, setSelected] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [locating, setLocating] = useState(false)
  const [driveMinutes, setDriveMinutes] = useState(45)
  const [driveActive, setDriveActive] = useState(false)
  const requestSeq = useRef(0)
  const sheet = useSheet()

  const runDrive = () => {
    if (!origin) {
      setError('Set a start point first — search, tap the map, or use your location.')
      return
    }
    const seq = ++requestSeq.current
    setLoading(true)
    setError(null)
    setDestination(null)
    fetchDrive(origin, driveMinutes)
      .then((d) => {
        if (requestSeq.current !== seq) return
        setDriveActive(true)
        // render the loop through the normal candidate pipeline
        setCandidates([
          { fun_dial: 1, dtime_s: 0, sought: null, ...d } as RouteCandidate,
        ])
        setSelected(0)
      })
      .catch((e: Error) => {
        if (requestSeq.current === seq) {
          setCandidates(null)
          setError(e.message)
        }
      })
      .finally(() => {
        if (requestSeq.current === seq) setLoading(false)
      })
  }

  const setPlace = (which: 'origin' | 'destination', place: Place | null) => {
    setError(null)
    setCandidates(null)
    setSelected(0)
    setDriveActive(false)
    if (which === 'origin') setOrigin(place)
    else setDestination(place)
  }

  const handleMapClick = (point: LatLng) => {
    const place = { ...point, label: `${point.lat.toFixed(4)}, ${point.lng.toFixed(4)}` }
    if (!origin) setPlace('origin', place)
    else if (!destination) setPlace('destination', place)
    else {
      // third click starts a fresh pair
      setDestination(null)
      setPlace('origin', place)
    }
  }

  const fromSearch = (which: 'origin' | 'destination') => (r: GeocodeResult) =>
    setPlace(which, { lat: r.lat, lng: r.lng, label: r.label })

  const useMyLocation = () => {
    setError(null)
    if (!('geolocation' in navigator)) {
      setError('This browser has no location support — search or click the map instead.')
      return
    }
    if (!window.isSecureContext) {
      setError(
        'Location needs HTTPS (or localhost). Until the tunnel is up, search or click the map instead.',
      )
      return
    }
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false)
        setPlace('origin', {
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          label: 'My location',
        })
      },
      () => {
        setLocating(false)
        setError('Could not get your location — search or click the map instead.')
      },
      { enableHighAccuracy: true, timeout: 8000 },
    )
  }

  const clear = () => {
    setOrigin(null)
    setDestination(null)
    setCandidates(null)
    setSelected(0)
    setError(null)
    setDriveActive(false)
  }

  useEffect(() => {
    if (!origin || !destination) return
    const seq = ++requestSeq.current
    setLoading(true)
    setError(null)
    fetchRoute(origin, destination)
      .then((r) => {
        if (requestSeq.current !== seq) return
        setCandidates(r.candidates)
        // preselect the funnest candidate that made the cut
        setSelected(r.candidates.length - 1)
      })
      .catch((e: Error) => {
        if (requestSeq.current === seq) {
          setCandidates(null)
          setError(e.message)
        }
      })
      .finally(() => {
        if (requestSeq.current === seq) setLoading(false)
      })
  }, [origin, destination])

  const routeLines: RouteLine[] = (candidates ?? []).map((c) => ({
    latlngs: c.coordinates.map(([lng, lat]) => [lat, lng] as [number, number]),
  }))
  const selectedCandidate = candidates && !loading ? candidates[selected] : null

  return (
    <>
      <MapView
        origin={origin}
        destination={destination}
        routes={routeLines}
        selectedIndex={selected}
        onSelectRoute={setSelected}
        onMapClick={handleMapClick}
      />
      <div
        ref={sheet.panelRef}
        className={`panel${sheet.collapsed ? ' collapsed' : ''}${sheet.dragging ? ' dragging' : ''}`}
        style={sheet.style}
      >
        <div
          className="grab-zone"
          role="button"
          tabIndex={0}
          aria-label={sheet.collapsed ? 'Show route options' : 'Hide route options'}
          aria-expanded={!sheet.collapsed}
          onClick={sheet.toggle}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              sheet.toggle()
            }
          }}
          {...sheet.handleProps}
        >
          <div className="grabber" aria-hidden="true" />
        </div>
        {/* only meaningful once the sheet is down over the map */}
        {selectedCandidate && (
          <button className="peek" onClick={sheet.expand}>
            <span className="peek-name">
              {selectedCandidate.sought ? 'Worth the detour' : dialLabel(selectedCandidate.fun_dial)}
            </span>
            <span className="peek-stats">
              {formatDistance(selectedCandidate.distance_m)} · {formatTime(selectedCandidate.time_s)}
              {selectedCandidate.dtime_s > 0 && (
                <em> +{Math.round(selectedCandidate.dtime_s / 60)} min</em>
              )}
            </span>
          </button>
        )}
        <div className="panel-title">
          <h1>
            <em>sassy</em>routes
          </h1>
        </div>
        <p className="tagline">The long way — on purpose.</p>
        <SearchBox
          placeholder="Origin — search or click the map"
          selectedLabel={origin?.label ?? null}
          onSelect={fromSearch('origin')}
        />
        <button className="locate" onClick={useMyLocation} disabled={locating}>
          {locating ? 'Locating…' : '◎ Use my location'}
        </button>
        <SearchBox
          placeholder="Destination — search or click the map"
          selectedLabel={destination?.label ?? null}
          onSelect={fromSearch('destination')}
        />
        <div className="drive">
          <span className="drive-or">or just go for a drive</span>
          <div className="drive-row">
            <label>
              <input
                type="number"
                min={15}
                max={240}
                step={15}
                value={driveMinutes}
                onChange={(e) => setDriveMinutes(Number(e.target.value))}
              />
              min
            </label>
            <button className="drive-go" onClick={runDrive} disabled={loading}>
              🎲 {driveActive ? 'Another one' : 'Surprise me'}
            </button>
          </div>
        </div>
        {loading && <p className="hint">{driveActive ? 'Planning your drive…' : 'Finding routes…'}</p>}
        {candidates && !loading && (
          <div className="candidates">
            {candidates.map((c, i) => (
              <button
                key={c.fun_dial}
                className={`candidate ${i === selected ? 'selected' : ''}`}
                onClick={() => setSelected(i)}
              >
                <span className="candidate-head">
                  <span className="candidate-name">
                    {driveActive
                      ? '🔁 Your loop'
                      : c.sought
                        ? 'Worth the detour'
                        : dialLabel(c.fun_dial)}
                  </span>
                  <span className="candidate-time">
                    {formatTime(c.time_s)}
                    {c.dtime_s > 0 && <em> +{Math.round(c.dtime_s / 60)} min</em>}
                  </span>
                </span>
                <span className="candidate-sub">
                  <span>{formatDistance(c.distance_m)}</span>
                  {c.fun_index !== null && (
                    <span className="funmeter" title={`Fun index ${c.fun_index}`}>
                      <span className="funbar" style={{ width: `${c.fun_index * 100}%` }} />
                    </span>
                  )}
                  {c.fun_index !== null && <span>{Math.round(c.fun_index * 100)}%</span>}
                </span>
                {c.sought && (
                  <span className="sought">
                    ★ routed via {c.sought.name ?? 'an unnamed road'} —{' '}
                    {Math.round(c.sought.fun_index * 100)}% fun,{' '}
                    {formatDistance(c.sought.length_m)}
                  </span>
                )}
                {c.why && (
                  <span className="criteria">
                    {criteriaChips(c.why).map((chip) => (
                      <span
                        key={chip.label}
                        className={chip.penalized ? 'chip flag' : 'chip'}
                        title={chip.title}
                      >
                        {chip.label} <b>{chip.value}</b>
                      </span>
                    ))}
                  </span>
                )}
                {c.why && c.why.scored_fraction < 0.9 && (
                  <span className="criteria-note">
                    scored on {Math.round(c.why.scored_fraction * 100)}% of the route
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
        {candidates && !loading && candidates[selected] && (
          <div className="handoff">
            <a
              className="open-maps"
              href={candidates[selected].handoff.maps_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => {
                const c = candidates[selected]
                postEvent({
                  type: 'maps_opened',
                  fun_dial: c.fun_dial,
                  fun_index: c.fun_index,
                  dtime_s: c.dtime_s,
                })
              }}
            >
              Open in Google Maps ↗
            </a>
            {!candidates[selected].handoff.pinned && (
              <p className="warn">
                Too twisty to pin with {candidates[selected].handoff.waypoints_used} waypoints
                — Google may reroute parts of it. Use the GPX for the exact route.
              </p>
            )}
            <button
              className="gpx"
              onClick={() =>
                downloadGpx(
                  candidates[selected].coordinates,
                  `sassy ${dialLabel(candidates[selected].fun_dial)} route`,
                )
              }
            >
              Download GPX
            </button>
          </div>
        )}
        {error && <p className="error">{error}</p>}
        {(origin || destination) && (
          <button className="clear" onClick={clear}>
            Clear
          </button>
        )}
        {candidates && !loading && candidates.some((c) => c.why) && (
          <details className="legend">
            <summary>What do these scores mean?</summary>
            <dl>
              <dt>Corners</dt>
              <dd>How much the route actually bends. The biggest factor (60%).</dd>
              <dt>Hills</dt>
              <dd>Elevation change along the way — rolling terrain rates higher (15%).</dd>
              <dt>Road type</dt>
              <dd>
                What kind of roads it uses. Rural backroads rate highest; highways,
                subdivision streets and service roads rate lowest (25%).
              </dd>
              <dt>Surface</dt>
              <dd>
                Paved check. Gravel and dirt cut the score hard — this is tuned for a low
                sports car.
              </dd>
              <dt>Safety</dt>
              <dd>
                Cuts the score where driveways and junctions are dense, or where tight
                curves sit on low-limit roads. It can only subtract, never add.
              </dd>
              <dt>★ Worth the detour</dt>
              <dd>
                A route sent deliberately through one standout road near your way. Short
                great roads barely move a whole route's average, so they get hunted
                separately.
              </dd>
            </dl>
            <p>
              Corners, Hills and Road type combine into the fun score. Surface and Safety
              are limits applied on top — they show in red when they reduced a route.
            </p>
          </details>
        )}
        <p className="fineprint">
          Drive responsibly — obey posted limits and traffic laws.
          <br />
          Routing &amp; search data ©{' '}
          <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors
          (ODbL). Routing by GraphHopper. Search by Photon.
        </p>
      </div>
    </>
  )
}

function dialLabel(dial: number): string {
  const hit = DIAL_LABELS.find(([d]) => Math.abs(d - dial) < 0.01)
  return hit ? hit[1] : `Fun ${Math.round(dial * 100)}%`
}

function formatDistance(meters: number): string {
  const miles = meters / 1609.344
  return `${miles.toFixed(1)} mi`
}

function formatTime(seconds: number): string {
  const totalMin = Math.round(seconds / 60)
  const h = Math.floor(totalMin / 60)
  const m = totalMin % 60
  return h > 0 ? `${h} h ${m} min` : `${m} min`
}
