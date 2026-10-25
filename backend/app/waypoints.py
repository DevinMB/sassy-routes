"""Waypoint compression for the Google Maps handoff (CLAUDE-ref §5).

Google re-routes *between* the waypoints we give it, so we must pick ≤ N
intermediate waypoints that pin it to our polyline.

Two stages:
  1. `compress` — WHICH detours need pinning. Risk metric is per-gap EXCESS
     PATH LENGTH (our path − straight chord): a smooth freeway curve sags far
     from a long chord yet Google follows it anyway, while a fun detour is
     exactly a stretch whose path length beats its chord — what Google's
     fastest-route preference would cut. Each such gap gets a waypoint.
  2. `refine_on_road` — WHERE on that detour the waypoint sits. compress puts
     it at the apex (sharpest bend), which is the worst place for Google to
     snap: sharp bends sit at junctions, so Google loops or U-turns to reach
     the point with a sane heading. Refinement slides it to the cleanest spot
     — far from any junction, on straight geometry — which pins just as well
     and snaps reliably.

Every waypoint lies on the route by construction. The optional verified mode
(verify.py) is the ground-truth check.
"""
import math


def project(coordinates: list) -> tuple[list[float], list[float]]:
    """Local equirectangular projection to meters (fine at route scale)."""
    lat0 = math.radians(sum(c[1] for c in coordinates) / len(coordinates))
    k_lng = 111_320.0 * math.cos(lat0)
    xs = [c[0] * k_lng for c in coordinates]
    ys = [c[1] * 110_540.0 for c in coordinates]
    return xs, ys


def _cumlen(xs: list, ys: list) -> list:
    cum = [0.0]
    for i in range(1, len(xs)):
        cum.append(cum[-1] + math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]))
    return cum


def compress(
    coordinates: list, max_waypoints: int, max_gap_excess_m: float
) -> tuple[list[int], float, bool]:
    """Returns (interior waypoint indices, worst remaining gap excess m, pinned)."""
    n = len(coordinates)
    if n <= 2:
        return [], 0.0, True
    xs, ys = project(coordinates)
    cum = _cumlen(xs, ys)

    chain = [0, n - 1]
    while len(chain) - 2 < max_waypoints:
        excess, gap = _worst_gap(xs, ys, cum, chain)
        if excess <= max_gap_excess_m:
            break
        chain.insert(gap + 1, _apex(xs, ys, chain[gap], chain[gap + 1]))

    final_excess, _ = _worst_gap(xs, ys, cum, chain)
    return chain[1:-1], round(final_excess, 1), final_excess <= max_gap_excess_m


def refine_on_road(
    coordinates: list,
    way_intervals: list,
    wp_indices: list[int],
    max_gap_excess_m: float,
    curve_penalty_m_per_deg: float,
    junction_clearance_m: float,
    center_window_frac: float,
) -> tuple[list[int], float, bool]:
    """Slide each waypoint to the cleanest spot near the middle of its detour.

    A waypoint pins its detour by sitting deep inside it, far from the *ends* —
    the shortcut points where Google would cut the corner. So we anchor at the
    detour's arc-length centre, then within a band around it (`center_window_
    frac` of the half-gap) pick the vertex that (a) isn't sitting on a mid-
    detour junction — where the OSM way id changes and Google snaps ambiguously,
    looping to reach it — and (b) is straightest, so the approach heading is
    unambiguous. Staying near centre keeps the pin; the band bounds how much
    pinning we'll trade for a clean snap.

    Returns (refined indices, worst gap excess m, pinned) recomputed against the
    moved points, so `pinned` stays honest.
    """
    n = len(coordinates)
    if not wp_indices:
        return wp_indices, 0.0, True
    xs, ys = project(coordinates)
    cum = _cumlen(xs, ys)
    junctions = _junction_positions(cum, way_intervals, n)

    refined: list[int] = []
    for k, idx in enumerate(wp_indices):
        lo = refined[-1] if refined else 0
        hi = wp_indices[k + 1] if k + 1 < len(wp_indices) else n - 1
        if hi - lo < 2:
            refined.append(idx)  # no interior vertex to move to
            continue
        center = (cum[lo] + cum[hi]) / 2
        window = center_window_frac * (cum[hi] - cum[lo]) / 2
        best_i, best_score = idx, -math.inf
        for i in range(lo + 1, hi):
            if abs(cum[i] - center) > window:
                continue  # too far from centre — would weaken the pin
            # reward being clear of a junction (capped: past the clearance
            # distance we stop caring), penalise turning
            jdist = min((abs(cum[i] - j) for j in junctions), default=junction_clearance_m)
            score = min(jdist, junction_clearance_m) - curve_penalty_m_per_deg * _turn_angle_deg(
                xs, ys, i
            )
            if score > best_score:
                best_score, best_i = score, i
        refined.append(best_i)

    excess, _ = _worst_gap(xs, ys, cum, [0, *refined, n - 1])
    return refined, round(excess, 1), excess <= max_gap_excess_m


def _junction_positions(cum: list, way_intervals: list, n: int) -> list:
    """Arc-length positions where the OSM way changes — i.e. real junctions.

    way_intervals is [[from_idx, to_idx, way_id], ...]; a junction sits at every
    interior interval boundary."""
    boundaries = set()
    for iv in way_intervals or []:
        for endpoint in (iv[0], iv[1]):
            if 0 < endpoint < n - 1:
                boundaries.add(endpoint)
    return sorted(cum[i] for i in boundaries)


def _turn_angle_deg(xs, ys, i: int) -> float:
    """Interior turn angle at vertex i in degrees (0 = straight through)."""
    ax, ay = xs[i] - xs[i - 1], ys[i] - ys[i - 1]
    bx, by = xs[i + 1] - xs[i], ys[i + 1] - ys[i]
    na, nb = math.hypot(ax, ay), math.hypot(bx, by)
    if na == 0 or nb == 0:
        return 0.0
    cos = max(-1.0, min(1.0, (ax * bx + ay * by) / (na * nb)))
    return math.degrees(math.acos(cos))


def _worst_gap(xs, ys, cum, chain) -> tuple[float, int]:
    """Gap with the largest (path length − chord length). Returns (excess_m, gap)."""
    worst, worst_gap = 0.0, -1
    for gap in range(len(chain) - 1):
        a, b = chain[gap], chain[gap + 1]
        chord = math.hypot(xs[b] - xs[a], ys[b] - ys[a])
        excess = (cum[b] - cum[a]) - chord
        if excess > worst:
            worst, worst_gap = excess, gap
    return worst, worst_gap


def _apex(xs, ys, a: int, b: int) -> int:
    """Vertex between a and b farthest from the a→b chord (the detour apex)."""
    best, best_idx = -1.0, a + 1
    for i in range(a + 1, b):
        d = _point_segment_m(xs[i], ys[i], xs[a], ys[a], xs[b], ys[b])
        if d > best:
            best, best_idx = d, i
    return best_idx


def _point_segment_m(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
