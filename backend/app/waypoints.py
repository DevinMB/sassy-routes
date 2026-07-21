"""Waypoint compression for the Google Maps handoff (CLAUDE-ref §5).

Google re-routes *between* the waypoints we give it, so we must pick ≤ N
intermediate waypoints that pin it to our polyline.

Risk metric: per-gap EXCESS PATH LENGTH (our path − straight chord). Corridor
deviation is the wrong proxy — a smooth freeway curve sags far from a long
chord yet Google follows it anyway (the sag *is* the road) — while a fun
detour is exactly a stretch whose path length beats its chord, i.e. what
Google's fastest-route preference would cut. Gaps with too much excess get a
waypoint at their maximum-sag vertex (the detour apex). Every waypoint lies on
the route by construction. The optional verified mode (verify.py) is the
ground-truth check.
"""
import math


def project(coordinates: list) -> tuple[list[float], list[float]]:
    """Local equirectangular projection to meters (fine at route scale)."""
    lat0 = math.radians(sum(c[1] for c in coordinates) / len(coordinates))
    k_lng = 111_320.0 * math.cos(lat0)
    xs = [c[0] * k_lng for c in coordinates]
    ys = [c[1] * 110_540.0 for c in coordinates]
    return xs, ys


def compress(
    coordinates: list, max_waypoints: int, max_gap_excess_m: float
) -> tuple[list[int], float, bool]:
    """Returns (interior waypoint indices, worst remaining gap excess m, pinned)."""
    n = len(coordinates)
    if n <= 2:
        return [], 0.0, True
    xs, ys = project(coordinates)
    # cumulative path length at each vertex
    cum = [0.0]
    for i in range(1, n):
        cum.append(cum[-1] + math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]))

    chain = [0, n - 1]
    while len(chain) - 2 < max_waypoints:
        excess, gap = _worst_gap(xs, ys, cum, chain)
        if excess <= max_gap_excess_m:
            break
        chain.insert(gap + 1, _apex(xs, ys, chain[gap], chain[gap + 1]))

    final_excess, _ = _worst_gap(xs, ys, cum, chain)
    return chain[1:-1], round(final_excess, 1), final_excess <= max_gap_excess_m


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
