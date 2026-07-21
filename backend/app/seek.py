"""Peak-seeking: route deliberately through short, genuinely great roads.

The fun index is a length-weighted average, which structurally ignores a
brilliant 300 m curve on a 40 km trip — routing through it moves the average by
~0.001, so plain edge weighting will never chase it. A driver very much wants
it. This module finds high-scoring segments near the straight-line corridor so
the router can be sent through one as a via-point.

Pure geometry + ranking here; the CouchDB lookup and the routing calls live in
their callers, which keeps this unit-testable.
"""
import math

from .geo import haversine_km


def corridor_cells(
    origin, destination, cell_size_deg: float, buffer_km: float
) -> list[list[int]]:
    """Grid cells covering the origin→destination corridor plus a buffer.

    Cells are the same [lat_cell, lng_cell] keys the pipeline stamps on each
    segment, so this is the key list for the `seek/by_cell` view.
    """
    lat_pad = buffer_km / 110.574
    mid_lat = math.radians((origin.lat + destination.lat) / 2)
    lng_pad = buffer_km / max(111.320 * math.cos(mid_lat), 1e-6)

    lat_lo = min(origin.lat, destination.lat) - lat_pad
    lat_hi = max(origin.lat, destination.lat) + lat_pad
    lng_lo = min(origin.lng, destination.lng) - lng_pad
    lng_hi = max(origin.lng, destination.lng) + lng_pad

    cells = []
    lat_cell = math.floor(lat_lo / cell_size_deg)
    while lat_cell <= math.floor(lat_hi / cell_size_deg):
        lng_cell = math.floor(lng_lo / cell_size_deg)
        while lng_cell <= math.floor(lng_hi / cell_size_deg):
            cells.append([lat_cell, lng_cell])
            lng_cell += 1
        lat_cell += 1
    return cells


def rank_targets(rows: list[dict], origin, destination, cfg_seek: dict) -> list[dict]:
    """Pick the best seek targets near the corridor, best first.

    A target must sit within the corridor buffer of the straight line and be
    long enough to be worth a detour. Ranking prefers the highest fun index,
    with length breaking ties — we want the *best* road, not the longest.
    """
    buffer_km = cfg_seek["corridor_buffer_km"]
    min_length_m = cfg_seek["min_length_m"]
    excluded = set(cfg_seek.get("exclude_highways") or ())

    targets = []
    for row in rows:
        value = row.get("value") or {}
        mid = value.get("mid")
        if not mid or value.get("length_m", 0) < min_length_m:
            continue
        # not a road you detour *to*, whatever its geometry says
        if (value.get("highway") or "").removesuffix("_link") in excluded:
            continue
        detour_km = _distance_to_segment_km(mid[0], mid[1], origin, destination)
        if detour_km > buffer_km:
            continue
        targets.append({
            "lat": mid[0],
            "lng": mid[1],
            "fun_index": value.get("fun", 0.0),
            "name": value.get("name"),
            "length_m": value.get("length_m", 0.0),
            "off_corridor_km": round(detour_km, 2),
        })

    targets.sort(key=lambda t: (-t["fun_index"], -t["length_m"]))
    return _dedupe_nearby(targets, cfg_seek["max_targets"])


def _dedupe_nearby(targets: list[dict], limit: int, min_gap_km: float = 1.0) -> list[dict]:
    """One target per neighbourhood — OSM splits a great road into many ways,
    and trying three slices of the same curve wastes routing calls."""
    kept: list[dict] = []
    for t in targets:
        if any(haversine_km(t["lat"], t["lng"], k["lat"], k["lng"]) < min_gap_km for k in kept):
            continue
        kept.append(t)
        if len(kept) >= limit:
            break
    return kept


def _distance_to_segment_km(lat, lng, origin, destination) -> float:
    """Perpendicular distance from a point to the origin→destination line."""
    # local equirectangular projection — fine at corridor scale
    lat0 = math.radians((origin.lat + destination.lat) / 2)
    kx = 111.320 * math.cos(lat0)
    ky = 110.574
    px, py = lng * kx, lat * ky
    ax, ay = origin.lng * kx, origin.lat * ky
    bx, by = destination.lng * kx, destination.lat * ky

    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
