"""Fun-cluster grid helpers.

Bucket the per-segment fun scores into the same ~2 km cells the routing model
uses, so the take-me-for-a-drive loop generator can aim its waypoints at
clusters of good roads. Pure grid math; the CouchDB read lives in the caller.
"""
import math


def bbox_cells(
    min_lat: float, min_lng: float, max_lat: float, max_lng: float,
    cell_size_deg: float, max_cells: int,
) -> list[list[int]]:
    """Grid cells covering a bounding box. Empty if the box would need more than
    max_cells — an unbounded area would be a CouchDB hammer (DoS guard)."""
    lat_lo, lat_hi = min(min_lat, max_lat), max(min_lat, max_lat)
    lng_lo, lng_hi = min(min_lng, max_lng), max(min_lng, max_lng)
    rows = math.floor(lat_hi / cell_size_deg) - math.floor(lat_lo / cell_size_deg) + 1
    cols = math.floor(lng_hi / cell_size_deg) - math.floor(lng_lo / cell_size_deg) + 1
    if rows * cols > max_cells:
        return []
    cells = []
    for la in range(math.floor(lat_lo / cell_size_deg), math.floor(lat_hi / cell_size_deg) + 1):
        for ln in range(math.floor(lng_lo / cell_size_deg), math.floor(lng_hi / cell_size_deg) + 1):
            cells.append([la, ln])
    return cells


def aggregate(rows: list[dict], cell_size_deg: float) -> list[dict]:
    """Sum fun × length per cell → cluster tiles (cell centre + weight)."""
    weights: dict[tuple[int, int], float] = {}
    for row in rows:
        key = row.get("key")
        value = row.get("value") or {}
        fun = value.get("fun", 0.0)
        length_m = value.get("length_m", 0.0)
        if not key or fun <= 0:
            continue
        cell = (key[0], key[1])
        weights[cell] = weights.get(cell, 0.0) + fun * length_m
    return [
        {
            "lat": round((la + 0.5) * cell_size_deg, 6),
            "lng": round((ln + 0.5) * cell_size_deg, 6),
            "weight": round(w, 1),
        }
        for (la, ln), w in weights.items()
    ]
