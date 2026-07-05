from pathlib import Path

import numpy as np
import pytest
import yaml

from scorer.score import curvature_score, elevation_score, parse_maxspeed_kmh, score_way

# Test against the real config — validates scoring.yaml's shape at the same time.
CFG = yaml.safe_load((Path(__file__).parents[2] / "scoring.yaml").read_text())


def no_junctions(n):
    return np.zeros(n, dtype=bool)


def straight_road(n=20, step=0.001):
    """North-south line, ~111 m between vertices."""
    lats = np.array([42.0 + i * step for i in range(n)])
    lngs = np.full(n, -84.0)
    return lats, lngs


def twisty_road(n=40, step=0.0005):
    """Sustained zigzag — alternating bearing changes every ~50 m."""
    lats = np.array([42.0 + i * step for i in range(n)])
    lngs = np.array([-84.0 + (0.0004 if i % 2 else 0.0) for i in range(n)])
    return lats, lngs


def test_straight_road_scores_zero_curvature():
    lats, lngs = straight_road()
    score, tight, length = curvature_score(lats, lngs, no_junctions(len(lats)), CFG)
    assert score == 0.0
    assert tight == 0.0
    assert length > 1000


def test_twisty_road_scores_high_curvature():
    lats, lngs = twisty_road()
    score, _, _ = curvature_score(lats, lngs, no_junctions(len(lats)), CFG)
    assert score > 0.3


def test_junctions_zero_out_nearby_curvature():
    lats, lngs = twisty_road()
    all_junctions = np.ones(len(lats), dtype=bool)  # driveway hell
    score, _, _ = curvature_score(lats, lngs, all_junctions, CFG)
    assert score == 0.0


def test_elevation_relief_earns_component():
    seg = np.full(10, 100.0)  # 1 km total
    rolling = np.array([100, 105, 98, 106, 99, 107, 100, 108, 101, 109, 102], dtype=float)
    flat = np.full(11, 100.0)
    assert elevation_score(rolling, seg, CFG) > 0.5
    assert elevation_score(flat, seg, CFG) == 0.0
    assert elevation_score(None, seg, CFG) == 0.0


def test_sustained_steep_caps_component():
    seg = np.full(10, 100.0)
    steep = np.array([100 + 12 * i for i in range(11)], dtype=float)  # 12% for 1 km
    assert elevation_score(steep, seg, CFG) <= CFG["elevation"]["sustained_steep"]["component_cap"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("55 mph", pytest.approx(88.5, abs=0.1)), ("70", 70.0), (None, None), ("walk", None)],
)
def test_parse_maxspeed(raw, expected):
    assert parse_maxspeed_kmh(raw) == expected


def test_unpaved_gate_kills_fun():
    lats, lngs = twisty_road()
    mask = no_junctions(len(lats))
    paved = score_way({"highway": "tertiary", "surface": "asphalt"}, lats, lngs, mask, None, CFG)
    gravel = score_way({"highway": "tertiary", "surface": "gravel"}, lats, lngs, mask, None, CFG)
    assert paved["fun_index"] > 0.3
    assert gravel["fun_index"] < 0.05


def test_low_limit_tight_geometry_penalized():
    lats, lngs = twisty_road()
    mask = no_junctions(len(lats))
    open_road = score_way({"highway": "tertiary"}, lats, lngs, mask, None, CFG)
    goat_path = score_way({"highway": "tertiary", "maxspeed": "25 mph"}, lats, lngs, mask, None, CFG)
    assert goat_path["fun_index"] < open_road["fun_index"]


def test_unknown_highway_skipped():
    lats, lngs = straight_road()
    assert score_way({"highway": "bridleway"}, lats, lngs, no_junctions(len(lats)), None, CFG) is None


def test_motorway_scores_below_tertiary():
    lats, lngs = twisty_road()
    mask = no_junctions(len(lats))
    tertiary = score_way({"highway": "tertiary", "surface": "asphalt"}, lats, lngs, mask, None, CFG)
    motorway = score_way({"highway": "motorway", "surface": "asphalt"}, lats, lngs, mask, None, CFG)
    assert motorway["fun_index"] < tertiary["fun_index"]