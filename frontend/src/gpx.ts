/** Client-side GPX export — the fallback when a route is too twisty to pin
 * with the Maps waypoint budget (and available always, for GPX-native apps). */

export function routeToGpx(coordinates: [number, number][], name: string): string {
  const pts = coordinates
    .map(([lng, lat]) => `      <trkpt lat="${lat.toFixed(6)}" lon="${lng.toFixed(6)}"/>`)
    .join('\n')
  return `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="sassy-routes" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>${escapeXml(name)}</name>
    <trkseg>
${pts}
    </trkseg>
  </trk>
</gpx>
`
}

export function downloadGpx(coordinates: [number, number][], name: string): void {
  const blob = new Blob([routeToGpx(coordinates, name)], { type: 'application/gpx+xml' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}.gpx`
  a.click()
  URL.revokeObjectURL(url)
}

function escapeXml(s: string): string {
  return s.replace(/[<>&'"]/g, (c) =>
    ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', "'": '&apos;', '"': '&quot;' })[c]!,
  )
}
