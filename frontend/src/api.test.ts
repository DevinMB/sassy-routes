import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchRoute, geocode } from './api'

const origin = { lat: 42.281, lng: -83.743 }
const destination = { lat: 42.331, lng: -83.046 }

afterEach(() => vi.unstubAllGlobals())

describe('fetchRoute', () => {
  it('posts origin/destination and parses the candidates', async () => {
    const payload = {
      candidates: [
        {
          fun_dial: 0, distance_m: 1000, time_s: 60, dtime_s: 0,
          fun_index: 0.4, coordinates: [[-83.7, 42.28]],
        },
        {
          fun_dial: 0.6, distance_m: 1400, time_s: 90, dtime_s: 30,
          fun_index: 0.7, coordinates: [[-83.7, 42.28]],
        },
      ],
    }
    const mock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), { status: 200 }),
    )
    vi.stubGlobal('fetch', mock)

    const route = await fetchRoute(origin, destination)

    expect(mock).toHaveBeenCalledWith('/api/route', expect.objectContaining({ method: 'POST' }))
    expect(JSON.parse(mock.mock.calls[0][1].body)).toEqual({ origin, destination })
    expect(route.candidates).toHaveLength(2)
    expect(route.candidates[1].dtime_s).toBe(30)
  })

  it('surfaces the backend detail message on error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'too far apart' }), { status: 422 }),
    ))
    await expect(fetchRoute(origin, destination)).rejects.toThrow('too far apart')
  })
})

describe('geocode', () => {
  it('url-encodes the query and unwraps results', async () => {
    const results = [{ label: 'Traverse City, Michigan', lat: 44.76, lng: -85.62, type: 'city' }]
    const mock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ results }), { status: 200 }),
    )
    vi.stubGlobal('fetch', mock)

    const out = await geocode('traverse city')

    expect(mock).toHaveBeenCalledWith('/api/geocode?q=traverse%20city')
    expect(out).toEqual(results)
  })

  it('throws the backend detail message on error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'geocoder is unreachable' }), { status: 502 }),
    ))
    await expect(geocode('traverse city')).rejects.toThrow('geocoder is unreachable')
  })
})
