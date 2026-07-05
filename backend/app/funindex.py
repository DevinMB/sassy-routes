"""Length-weighted route fun index from per-segment CouchDB scores."""
from .geo import haversine_km


def route_fun_index(
    coordinates: list,
    way_intervals: list,
    segment_fun: dict[int, float] | None,
    default_fun: float,
) -> float | None:
    """Weight each way interval's fun_index by its polyline length.

    segment_fun None ⇒ CouchDB unavailable ⇒ report null rather than a made-up
    number. Ways missing from the db (unscored) fall back to default_fun.
    """
    if segment_fun is None or not way_intervals or len(coordinates) < 2:
        return None
    weighted = 0.0
    total = 0.0
    for from_idx, to_idx, way_id in way_intervals:
        length = _interval_km(coordinates, from_idx, to_idx)
        if length <= 0:
            continue
        fun = segment_fun.get(way_id, default_fun) if way_id is not None else default_fun
        weighted += fun * length
        total += length
    if total <= 0:
        return None
    return round(weighted / total, 3)


def _interval_km(coordinates: list, from_idx: int, to_idx: int) -> float:
    km = 0.0
    for i in range(max(from_idx, 0), min(to_idx, len(coordinates) - 1)):
        lng1, lat1 = coordinates[i][0], coordinates[i][1]
        lng2, lat2 = coordinates[i + 1][0], coordinates[i + 1][1]
        km += haversine_km(lat1, lng1, lat2, lng2)
    return km
