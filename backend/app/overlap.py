"""Out-and-back detection: how much of a route gets driven twice.

A route that runs up a road and turns back down it is one nobody wants to
drive, and it is invisible to every other metric we compute — distance, time
and fun index all look perfectly normal. Measuring it explicitly is what lets
the seek budget charge for it and the drive loop selector avoid it.

Undirected by design: driving a road out and back is the shape we care about,
and that traverses each underlying edge once in each direction.

Pure geometry, no I/O — the callers own the routing and the config.
"""
from .geo import haversine_km

# Coordinates come back from GraphHopper as the graph's own node positions, so
# a re-traversed edge yields bit-identical floats. Rounding to ~0.1 m guards
# against JSON round-trip noise without merging genuinely distinct nodes.
_PRECISION = 6


def _edge_key(a, b) -> tuple:
    """Order-independent key for the edge between two [lng, lat] points."""
    pa = (round(a[0], _PRECISION), round(a[1], _PRECISION))
    pb = (round(b[0], _PRECISION), round(b[1], _PRECISION))
    return (pa, pb) if pa <= pb else (pb, pa)


def retraversed_m(coordinates: list) -> float:
    """Metres of this route covered more than once, in either direction.

    A stretch driven twice counts once; driven three times, twice — i.e. this
    is the distance that would disappear if the repeats were removed.
    """
    seen: set = set()
    repeated = 0.0
    for i in range(len(coordinates) - 1):
        a, b = coordinates[i], coordinates[i + 1]
        key = _edge_key(a, b)
        if key in seen:
            # haversine takes (lat, lng); GeoJSON coordinates are [lng, lat]
            repeated += haversine_km(a[1], a[0], b[1], b[0]) * 1000.0
        else:
            seen.add(key)
    return repeated


def retraversal_penalty_s(
    coordinates: list,
    minutes_per_km: float,
    fixed_minutes: float = 0.0,
    ignore_m: float = 0.0,
) -> float:
    """Time penalty charged for re-driven road, in seconds.

    Two parts, because doubling back has two costs. `minutes_per_km` prices how
    *much* road is re-driven; `fixed_minutes` prices the fact that it happened
    at all, and is charged in full for any repeat above `ignore_m`.

    The fixed part is what the per-km rate alone cannot express. A route that
    overshoots the road it wanted by 122 m and turns back is the single most
    obviously-broken thing a driver sees on the map, and it is *cheap* by
    distance — 3.7 min at 30 min/km, waved through by a 25 min detour budget.
    That is exactly how one reached a user. Measured across real routes the
    distinction is stark and needs no cleverness to find: every route with the
    defect re-drove 122-4701 m, while every good seek candidate re-drove
    precisely 0 m. So the signal was never the problem — the pricing was.

    (A shape-based U-turn detector was tried first and dropped. Sweeping a
    heading window over the polyline read a genuine ~95° corner as a 144°
    reversal, and separating that from the real 170° turnaround needed a second
    threshold fitted to a handful of samples — a bad trade when the mechanism
    below already separates every observed case exactly, and when the roads a
    mis-fire would reject are the switchbacks this app exists to find.)

    `ignore_m` absorbs a stray metre of shared geometry at a junction without
    triggering the fixed charge.

    Still a penalty and not a ban: a genuinely spectacular dead-end road can be
    worth doubling back for, so this stays a weight the budget can outbid (an
    ordinary spur simply can't outbid it at the configured rates).
    """
    repeated_m = retraversed_m(coordinates)
    if repeated_m <= ignore_m:
        return 0.0
    return (repeated_m / 1000.0 * minutes_per_km + fixed_minutes) * 60.0
