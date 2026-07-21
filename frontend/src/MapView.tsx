import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { LatLng } from './api'

export interface RouteLine {
  /** Leaflet order: [lat, lng] pairs */
  latlngs: [number, number][]
}

interface Props {
  origin: LatLng | null
  destination: LatLng | null
  routes: RouteLine[]
  selectedIndex: number
  onSelectRoute: (index: number) => void
  onMapClick: (point: LatLng) => void
}

// Centered on Michigan's lower peninsula (Phase 0 extract).
const INITIAL_CENTER: [number, number] = [43.9, -84.8]
const INITIAL_ZOOM = 7

// matches --accent in index.css so the chosen route reads as "the fun one"
const SELECTED_STYLE = { color: '#e2590b', weight: 6, opacity: 0.95 }
const UNSELECTED_STYLE = { color: '#7b8b98', weight: 4, opacity: 0.55 }

export default function MapView({
  origin,
  destination,
  routes,
  selectedIndex,
  onSelectRoute,
  onMapClick,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const originMarkerRef = useRef<L.CircleMarker | null>(null)
  const destMarkerRef = useRef<L.CircleMarker | null>(null)
  const routeLinesRef = useRef<L.Polyline[]>([])
  const clickHandlerRef = useRef(onMapClick)
  const selectHandlerRef = useRef(onSelectRoute)
  clickHandlerRef.current = onMapClick
  selectHandlerRef.current = onSelectRoute

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return
    const map = L.map(containerRef.current, { zoomControl: false }).setView(
      INITIAL_CENTER,
      INITIAL_ZOOM,
    )
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map)
    map.on('click', (e: L.LeafletMouseEvent) =>
      clickHandlerRef.current({ lat: e.latlng.lat, lng: e.latlng.lng }),
    )
    mapRef.current = map
    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  // circle markers avoid the classic leaflet-icon-assets-under-bundlers mess
  useEffect(() => {
    syncMarker(mapRef.current, originMarkerRef, origin, '#2e7d32')
  }, [origin])

  useEffect(() => {
    syncMarker(mapRef.current, destMarkerRef, destination, '#c62828')
  }, [destination])

  // redraw candidate polylines when the set changes; fit bounds to all
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    routeLinesRef.current.forEach((l) => l.remove())
    routeLinesRef.current = routes.map((route, i) => {
      const line = L.polyline(route.latlngs, UNSELECTED_STYLE).addTo(map)
      line.on('click', (e) => {
        L.DomEvent.stopPropagation(e)
        selectHandlerRef.current(i)
      })
      return line
    })
    if (routes.length > 0) {
      const bounds = routeLinesRef.current
        .map((l) => l.getBounds())
        .reduce((a, b) => a.extend(b))
      // keep the route clear of the panel: side card on desktop, bottom sheet
      // on mobile, so the padding has to move with the layout
      const sheet = window.matchMedia('(max-width: 640px)').matches
      map.fitBounds(bounds, {
        paddingTopLeft: sheet ? [30, 30] : [360, 40],
        paddingBottomRight: sheet ? [30, Math.round(window.innerHeight * 0.55)] : [40, 40],
      })
    }
  }, [routes])

  // highlight selection without re-fitting (less jumpy)
  useEffect(() => {
    routeLinesRef.current.forEach((line, i) => {
      line.setStyle(i === selectedIndex ? SELECTED_STYLE : UNSELECTED_STYLE)
      if (i === selectedIndex) line.bringToFront()
    })
  }, [selectedIndex, routes])

  return <div ref={containerRef} className="map" />
}

function syncMarker(
  map: L.Map | null,
  ref: React.MutableRefObject<L.CircleMarker | null>,
  point: LatLng | null,
  color: string,
) {
  if (!map) return
  ref.current?.remove()
  ref.current = null
  if (point) {
    ref.current = L.circleMarker([point.lat, point.lng], {
      radius: 8,
      color,
      fillColor: color,
      fillOpacity: 0.85,
    }).addTo(map)
  }
}
