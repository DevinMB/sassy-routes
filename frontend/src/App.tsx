import { useEffect, useRef, useState } from 'react'
import { fetchRoute, type GeocodeResult, type LatLng, type RouteCandidate } from './api'
import MapView, { type RouteLine } from './MapView'
import SearchBox from './SearchBox'

interface Place extends LatLng {
  label: string
}

const DIAL_LABELS: [number, string][] = [
  [0.0, 'Fastest'],
  [0.3, 'A bit fun'],
  [0.6, 'Fun'],
  [0.9, 'Funnest'],
]

export default function App() {
  const [origin, setOrigin] = useState<Place | null>(null)
  const [destination, setDestination] = useState<Place | null>(null)
  const [candidates, setCandidates] = useState<RouteCandidate[] | null>(null)
  const [selected, setSelected] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [locating, setLocating] = useState(false)
  const requestSeq = useRef(0)

  const setPlace = (which: 'origin' | 'destination', place: Place | null) => {
    setError(null)
    setCandidates(null)
    setSelected(0)
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
      <div className="panel">
        <h1>sassy-routes</h1>
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
        {loading && <p className="hint">Finding routes…</p>}
        {candidates && !loading && (
          <div className="candidates">
            {candidates.map((c, i) => (
              <button
                key={c.fun_dial}
                className={`candidate ${i === selected ? 'selected' : ''}`}
                onClick={() => setSelected(i)}
              >
                <span className="candidate-head">
                  <span className="candidate-name">{dialLabel(c.fun_dial)}</span>
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
              </button>
            ))}
          </div>
        )}
        {error && <p className="error">{error}</p>}
        {(origin || destination) && <button onClick={clear}>Clear</button>}
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
