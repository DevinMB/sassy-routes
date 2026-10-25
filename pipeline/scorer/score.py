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
    vertices within conflict radius (along the line) of a junction are
    discounted to near_junction_weight (a curve at a blind driveway is a
    hazard, not fun). All junctions count here — including the way's endpoints,
    which are real intersections — but the discount is partial, because OSM
    splits ways at junctions and a hard zero erased short ways entirely.
    """
    seg = haversine_m(lats[:-1], lngs[:-1], lats[1:], lngs[1:])
    length_m = float(seg.sum())
    if len(lats) < 3 or length_m <= 0:
        return 0.0, 0.0, length_m

    turn = np.abs(np.diff(bearings_deg(lats, lngs)))
    turn = np.minimum(turn, 360.0 - turn)  # interior angles, [0, 180]
    local_len = (seg[:-1] + seg[1:]) / 2.0
    rate = np.where(local_len > 1e-6, turn / (local_len / 100.0), 0.0)

    # conflict-point discount: distance along the way to the nearest junction
    conflict = cfg["conflict_points"]
    radius = conflict["radius_m"]
    s = np.concatenate([[0.0], np.cumsum(seg)])  # position of each vertex
    junction_s = s[junction_mask]
    if len(junction_s):
        idx = np.searchsorted(junction_s, s[1:-1])
        left = np.where(idx > 0, s[1:-1] - junction_s[np.maximum(idx - 1, 0)], np.inf)
        right = np.where(
            idx < len(junction_s), junction_s[np.minimum(idx, len(junction_s) - 1)] - s[1:-1], np.inf
        )
        near = np.minimum(left, right) <= radius
        keep = np.where(near, conflict["near_junction_weight"], 1.0)
    else:
        keep = np.ones(len(rate))

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
    # rescale against the practical ceiling (see scoring.yaml) so a genuinely
    # curvy road reads near 1.0 instead of ~0.4
    score /= cfg["curvature"]["full_score_fraction"]
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
    rc_cfg = cfg["road_class"]
    class_score = rc_cfg.get(base_class)
    if class_score is None:
        return None

    curv, tight_fraction, length_m = curvature_score(lats, lngs, junction_mask, cfg)
    if length_m <= 0:
        return None
    seg = haversine_m(lats[:-1], lngs[:-1], lats[1:], lngs[1:])
    elev = elevation_score(elevs, seg, cfg)

    # Access density counts INTERIOR junctions only. A way's endpoints are
    # junctions by construction (OSM splits roads at intersections), so
    # including them roughly triples apparent density and made the safety gate
    # fire on almost everything rather than on genuinely driveway-dense roads.
    interior_junctions = junction_mask[1:-1]
    junctions_per_km = float(interior_junctions.sum()) / max(length_m / 1000.0, 0.05)
    maxspeed = parse_maxspeed_kmh(tags.get("maxspeed"))
    if maxspeed is None and base_class in ("residential", "living_street"):
        # Most US residential streets carry no maxspeed tag at all — it's an
        # unsigned legal default, not "no limit". Assume it rather than
        # letting untagged ways skip the safety gate below entirely.
        maxspeed = rc_cfg["residential_open_max_speed_kmh"]

    # Partial relax of the residential penalty: a slow, low-access-density
    # residential way reads as an open curvy street, not a subdivision maze.
    # The tight-curve-at-low-limit safety gate below still applies on top.
    if base_class == "residential":
        speed_ok = maxspeed <= rc_cfg["residential_open_max_speed_kmh"]
        density_ok = junctions_per_km <= rc_cfg["residential_open_max_junction_density_per_km"]
        if speed_ok and density_ok:
            class_score = rc_cfg["residential_open"]

    # Dead end: an endpoint that no other way shares. You cannot drive through
    # a cul-de-sac, so it is not a fun road.
    dead_end = not (bool(junction_mask[0]) and bool(junction_mask[-1]))
    if dead_end:
        class_score = rc_cfg["dead_end"]

    blend = cfg["blend"]
    fun = blend["curvature"] * curv + blend["elevation"] * elev + blend["road_class"] * class_score

    # Road-class gate: the veto the blend component above cannot express.
    # `class_score` carries only blend.road_class (0.25) of the total, so
    # `service: 0.0` docks a parking aisle a quarter of its score while its
    # tight corners saturate the 0.60-weighted curvature term — it still came
    # out at 0.755 and 79% of the seek index was service road. Classes that are
    # never worth driving have to be able to lose on class alone.
    class_gate = rc_cfg["gate"].get(base_class, 1.0)
    if dead_end:
        class_gate = min(class_gate, rc_cfg["gate"]["dead_end"])

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
    if junctions_per_km > safety["junction_density_per_km_threshold"]:
        safety_gate *= safety["dense_access_multiplier"]
    if (
        maxspeed is not None
        and maxspeed <= safety["low_speed_limit_kmh"]
        and tight_fraction > safety["tight_fraction_threshold"]
    ):
        safety_gate *= safety["low_limit_tight_multiplier"]

    fun_index = max(0.0, min(1.0, fun * surface_gate * safety_gate * class_gate))
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
        "gates": {
            "surface": surface_gate,
            "safety": round(safety_gate, 3),
            "road_class": class_gate,
        },
    }
