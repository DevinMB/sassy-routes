import math
import random

from app.drive import (
    forward_point,
    loop_aim_points,
    nearest_tile,
    target_radius_km,
)
from app.geo import haversine_km

DCFG = {
    "avg_speed_kmh": 60,
    "radius_fraction": 0.30,
    "radius_jitter": 0.20,
    "bearing_separation_deg": [45, 120],
    "snap_max_km": 10,
}


def test_forward_point_lands_at_the_right_distance_and_bearing():
    lat, lng = forward_point(42.0, -84.0, 90.0, 10.0)  # due east 10 km
    assert haversine_km(42.0, -84.0, lat, lng) == __import__("pytest").approx(10.0, abs=0.05)
    assert lat == __import__("pytest").approx(42.0, abs=0.01)  # east stays ~same lat
    assert lng > -84.0  # moved east


def test_target_radius_scales_with_time():
    # 60 min at 60 km/h = 60 km total, ×0.30 per leg = 18 km
    assert target_radius_km(60, DCFG) == 18.0
    assert target_radius_km(30, DCFG) == 9.0


def test_aim_points_are_two_and_separated():
    rng = random.Random(1)
    aims = loop_aim_points(42.0, -84.0, 18.0, DCFG, rng)
    assert len(aims) == 2
    # both roughly a leg-radius out (within jitter)
    for a in aims:
        d = haversine_km(42.0, -84.0, a[0], a[1])
        assert 18.0 * 0.8 - 0.5 <= d <= 18.0 * 1.2 + 0.5
    # and not the same bearing — the two aim points are apart
    assert haversine_km(aims[0][0], aims[0][1], aims[1][0], aims[1][1]) > 5.0


def test_drive_is_randomized_across_calls():
    # different seeds → different loops (keeps it fresh)
    a = loop_aim_points(42.0, -84.0, 18.0, DCFG, random.Random(1))
    b = loop_aim_points(42.0, -84.0, 18.0, DCFG, random.Random(2))
    assert a != b


def test_nearest_tile_snaps_within_range_and_prefers_fun():
    tiles = [
        {"lat": 42.05, "lng": -84.0, "weight": 100},   # close, low fun
        {"lat": 42.06, "lng": -84.0, "weight": 9000},  # close, high fun
        {"lat": 43.5, "lng": -84.0, "weight": 9999},   # great but far away
    ]
    rng = random.Random(0)
    picks = [nearest_tile(42.0, -84.0, tiles, max_km=10, rng=rng) for _ in range(30)]
    # never the far one (out of range)
    assert all(p["lat"] < 43 for p in picks)
    # weighted toward the high-fun close tile
    high = sum(1 for p in picks if p["weight"] == 9000)
    assert high > 15


def test_nearest_tile_returns_none_when_nothing_in_range():
    tiles = [{"lat": 43.5, "lng": -84.0, "weight": 9999}]
    assert nearest_tile(42.0, -84.0, tiles, max_km=10, rng=random.Random(0)) is None
