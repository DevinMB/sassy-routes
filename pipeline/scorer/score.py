"""Per-way fun scoring. Pure numpy math — no I/O — so it's unit-testable.

fun_index = blend(curvature, elevation, road_class) × surface_gate × safety_gate
All weights/thresholds come from scoring.yaml (guardrail 5).
"""
import numpy as np

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1, lng1, lat2, lng2):
    """Vectorized great-circle distance in meters."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(lng2) - np.radians(lng1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def bearings_deg(lats, lngs):
    """Forward bearing of each polyline segment, degrees in [0, 360)."""
    p1, p2 = np.radians(lats[:-1]), np.radians(lats[1:])
    dl = np.radians(lngs[1:] - lngs[:-1])
    y = np.sin(dl) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return np.degrees(np.arctan2(y, x)) % 360.0


def curvature_score(lats, lngs, junction_mask, cfg) -> tuple[float, float, float]:
    """Returns (score ∈ [0,1], tight_fraction, length_m).

    Interior vertices are binned by angular change per 100 m of local length;
    vertices within conflict radius (along the line) of a junction contribute
    zero (a curve at a blind driveway is a hazard, not fun).
    """
    seg = haversine_m(lats[:-1], lngs[:-1], lats[1:], lngs[1:])
    length_m = float(seg.sum())
    if len(lats) < 3 or length_m <= 0:
        return 0.0, 0.0, length_m

    turn = np.abs(np.diff(bearings_deg(lats, lngs)))
    turn = np.minimum(turn, 360.0 - turn)  # interior angles, [0, 180]
    local_len = (seg[:-1] + seg[1:]) / 2.0
    rate = np.where(local_len > 1e-6, turn / (local_len / 100.0), 0.0)

    # conflict-point zeroing: distance along the way to the nearest junction
    radius = cfg["conflict_points"]["radius_m"]
    s = np.concatenate([[0.0], np.cumsum(seg)])  # position of each vertex
    junction_s = s[junction_mask]
    if len(junction_s):
        idx = np.searchsorted(junction_s, s[1:-1])
        left = np.where(idx > 0, s[1:-1] - junction_s[np.maximum(idx - 1, 0)], np.inf)
        right = np.where(
            idx < len(junction_s), junction_s[np.minimum(idx, len(junction_s) - 1)] - s[1:-1], np.inf
        )
        keep = np.minimum(left, right) > radius
    else:
        keep = np.ones(len(rate), dtype=bool)

    bins = cfg["curvature"]["bins"]
    weights = np.zeros(len(rate))
    lower = 0.0
    tight_len = 0.0
    tight_threshold = bins["sweeper"]["max_deg_per_100m"]  # above sweeper = tight/hairpin
    for spec in bins.values():
        upper = float(spec["max_deg_per_100m"])
        in_bin = (rate > lower) & (rate <= upper)
        weights[in_bin] = spec["weight"]
        lower = upper
    tight_len = float(local_len[(rate > tight_threshold)].sum())

    score = float((weights * local_len * keep).sum() / length_m)
    return min(score, 1.0), tight_len / length_m, length_m


def elevation_score(elevs, seg_lengths, cfg) -> float:
    """Relief earns fun up to a cap; sustained steep grade caps the component."""
    ecfg = cfg["elevation"]
    total_m = float(seg_lengths.sum())
    if elevs is None or total_m <= 0 or len(elevs) < 2:
        return 0.0
    dz = np.diff(elevs)
    with np.errstate(divide="ignore", invalid="ignore"):
        grade = np.where(seg_lengths > 1e-6, 100.0 * dz / seg_lengths, 0.0)
    grade = np.clip(grade, -ecfg["max_grade_pct"], ecfg["max_grade_pct"])
    dz_clipped = grade / 100.0 * seg_lengths

    relief_per_km = float(np.abs(dz_clipped).sum() / (total_m / 1000.0))
    component = min(relief_per_km / ecfg["relief_full_score_m_per_km"], 1.0)

    steep = ecfg["sustained_steep"]
    steep_len = float(seg_lengths[np.abs(grade) > steep["grade_pct"]].sum())
    if steep_len > steep["length_m"]:
        component = min(component, steep["component_cap"])
    return component


def parse_maxspeed_kmh(value: str | None) -> float | None:
    if not value:
        return None
    v = value.strip().lower()
    try:
        if v.endswith("mph"):
            return float(v[:-3].strip()) * 1.609344
        return float(v)
    except ValueError:
        return None


def score_way(tags: dict, lats, lngs, junction_mask, elevs, cfg) -> dict | None:
    """Full fun score for one way. Returns a CouchDB doc body, or None to skip."""
    highway = tags.get("highway", "")
    base_class = highway.removesuffix("_link")
    class_score = cfg["road_class"].get(base_class)
    if class_score is None:
        return None

    curv, tight_fraction, length_m = curvature_score(lats, lngs, junction_mask, cfg)
    if length_m <= 0:
        return None
    seg = haversine_m(lats[:-1], lngs[:-1], lats[1:], lngs[1:])
    elev = elevation_score(elevs, seg, cfg)

    blend = cfg["blend"]
    fun = blend["curvature"] * curv + blend["elevation"] * elev + blend["road_class"] * class_score

    # surface gate (Miata rule)
    scfg = cfg["surface"]
    surface = tags.get("surface", "").split(":")[0]
    if surface in scfg["unpaved_values"] or tags.get("tracktype") not in (None, "grade1"):
        surface_gate = scfg["unpaved_multiplier"]
    elif surface == "":
        surface_gate = scfg["unknown_multiplier"]
    else:
        surface_gate = 1.0

    # safety gate (guardrail 4: dangerous geometry scores DOWN)
    safety = cfg["safety"]
    safety_gate = 1.0
    junctions_per_km = float(junction_mask.sum()) / max(length_m / 1000.0, 0.05)
    if junctions_per_km > safety["junction_density_per_km_threshold"]:
        safety_gate *= safety["dense_access_multiplier"]
    maxspeed = parse_maxspeed_kmh(tags.get("maxspeed"))
    if (
        maxspeed is not None
        and maxspeed <= safety["low_speed_limit_kmh"]
        and tight_fraction > safety["tight_fraction_threshold"]
    ):
        safety_gate *= safety["low_limit_tight_multiplier"]

    fun_index = max(0.0, min(1.0, fun * surface_gate * safety_gate))
    return {
        "type": "segment",
        "fun_index": round(fun_index, 4),
        "length_m": round(length_m, 1),
        "highway": highway,
        "name": tags.get("name"),
        "components": {
            "curvature": round(curv, 4),
            "elevation": round(elev, 4),
            "road_class": class_score,
        },
        "gates": {"surface": surface_gate, "safety": round(safety_gate, 3)},
    }
