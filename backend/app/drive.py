"""Take-me-for-a-drive: a randomized fun loop for a time budget.

"I've got 45 minutes — send me somewhere good and bring me back." We aim two
waypoints at high-fun clusters (the same per-cell fun data the routing model
scores) on a random bearing, forming a loop of roughly the right size, and route the legs
with the fun model so the road *between* clusters is good too. Randomised so
each run differs.

Pure geometry + selection here; the CouchDB read and routing calls live in the
caller, keeping this unit-testable and deterministic under a seeded RNG.
"""
import math
import random

from .geo import haversine_km

EARTH_KM = 6371.0


def forward_point(lat: float, lng: float, bearing_deg: float, distance_km: float) -> tuple[float, float]:
    """Point `distance_km` from (lat,lng) along `bearing_deg` (spherical)."""
    d = distance_km / EARTH_KM
    br = math.radians(bearing_deg)
    p1 = math.radians(lat)
    l1 = math.radians(lng)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(br))
    l2 = l1 + math.atan2(
        math.sin(br) * math.sin(d) * math.cos(p1),
        math.cos(d) - math.sin(p1) * math.sin(p2),
    )
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def loop_aim_points(
    origin_lat: float, origin_lng: float, radius_km: float, cfg_drive: dict, rng: random.Random
) -> list[tuple[float, float]]:
    """Two aim points at ~radius_km on a random bearing, separated so the
    origin→A→B→origin triangle is a loop rather than an out-and-back."""
    base = rng.uniform(0, 360)
    sep_lo, sep_hi = cfg_drive["bearing_separation_deg"]
    sep = rng.uniform(sep_lo, sep_hi)
    jitter = cfg_drive["radius_jitter"]
    a = forward_point(origin_lat, origin_lng, base, radius_km * rng.uniform(1 - jitter, 1 + jitter))
    b = forward_point(origin_lat, origin_lng, base + sep, radius_km * rng.uniform(1 - jitter, 1 + jitter))
    return [a, b]


def nearest_tile(lat: float, lng: float, tiles: list[dict], max_km: float, rng: random.Random) -> dict | None:
    """A high-fun tile near (lat,lng): weighted-random among the closest few, so
    aim points don't always snap to the single nearest cluster."""
    near = [
        (haversine_km(lat, lng, t["lat"], t["lng"]), t)
        for t in tiles
        if haversine_km(lat, lng, t["lat"], t["lng"]) <= max_km
    ]
    if not near:
        return None
    near.sort(key=lambda x: x[0])
    pool = [t for _, t in near[:5]]
    weights = [t["weight"] for t in pool]
    return rng.choices(pool, weights=weights, k=1)[0]


def target_radius_km(duration_min: float, cfg_drive: dict) -> float:
    """Per-leg radius so origin→A→B→origin totals roughly the time budget.

    total ≈ 3 legs of ~radius, so radius ≈ target_distance / 3."""
    target_km = duration_min / 60.0 * cfg_drive["avg_speed_kmh"]
    return target_km * cfg_drive["radius_fraction"]
