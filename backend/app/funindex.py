"""Length-weighted route fun index, plus the per-criterion breakdown behind it.

The breakdown surfaces the same five criteria the offline scorer uses
(scoring.yaml): the three blended components — curvature, elevation,
road_class — and the two multiplicative gates — surface, safety. Showing them
is what makes the fun number auditable instead of magic.
"""
from .geo import haversine_km

COMPONENTS = ("curvature", "elevation", "road_class")
GATES = ("surface", "safety")


def summarize_route(
    coordinates: list,
    way_intervals: list,
    segment_docs: dict[int, dict] | None,
    default_fun: float,
) -> tuple[float | None, dict | None]:
    """Returns (fun_index, why).

    segment_docs None ⇒ CouchDB unavailable ⇒ both None rather than a
    made-up number. Ways missing from the db (unscored) count toward the fun
    index at default_fun but are excluded from the breakdown, so unscored
    stretches dilute neither direction.
    """
    if segment_docs is None or not way_intervals or len(coordinates) < 2:
        return None, None

    # Aggregate length per way first — GraphHopper can emit the same way over
    # several intervals, and we want each way counted once by total length.
    lengths: dict[int | None, float] = {}
    for from_idx, to_idx, way_id in way_intervals:
        km = _interval_km(coordinates, from_idx, to_idx)
        if km > 0:
            lengths[way_id] = lengths.get(way_id, 0.0) + km

    total_km = sum(lengths.values())
    if total_km <= 0:
        return None, None

    weighted_fun = 0.0
    scored_km = 0.0
    sums = {key: 0.0 for key in (*COMPONENTS, *GATES)}

    for way_id, km in lengths.items():
        doc = segment_docs.get(way_id) if way_id is not None else None
        if doc is None:
            weighted_fun += default_fun * km
            continue
        weighted_fun += doc.get("fun_index", default_fun) * km
        scored_km += km
        components = doc.get("components") or {}
        gates = doc.get("gates") or {}
        for key in COMPONENTS:
            sums[key] += float(components.get(key, 0.0)) * km
        for key in GATES:
            # a missing gate means "not penalized"
            sums[key] += float(gates.get(key, 1.0)) * km

    fun_index = round(weighted_fun / total_km, 3)
    if scored_km <= 0:
        return fun_index, None
    why = {key: round(value / scored_km, 3) for key, value in sums.items()}
    # share of the route we actually have scores for — context for the rest
    why["scored_fraction"] = round(scored_km / total_km, 3)
    return fun_index, why


def _interval_km(coordinates: list, from_idx: int, to_idx: int) -> float:
    km = 0.0
    for i in range(max(from_idx, 0), min(to_idx, len(coordinates) - 1)):
        lng1, lat1 = coordinates[i][0], coordinates[i][1]
        lng2, lat2 = coordinates[i + 1][0], coordinates[i + 1][1]
        km += haversine_km(lat1, lng1, lat2, lng2)
    return km
