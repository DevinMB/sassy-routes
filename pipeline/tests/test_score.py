from pathlib import Path

import numpy as np
import pytest
import yaml

from scorer.score import curvature_score, elevation_score, parse_maxspeed_kmh, score_way

# Test against the real config — validates scoring.yaml's shape at the same time.
CFG = yaml.safe_load((Path(__file__).parents[2] / "scoring.yaml").read_text())


def no_junctions(n):
    """No junctions anywhere — for curvature tests, where the mask only
    controls conflict-point discounting."""
    return np.zeros(n, dtype=bool)


def through_road(n):
    """Junction at each end and nowhere else: a normal road segment. This is
    the realistic default for score_way — a way with NO junction at an endpoint
    is a dead end, which the model deliberately rejects."""
    mask = np.zeros(n, dtype=bool)
    mask[0] = mask[-1] = True
    return mask


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


def test_junctions_discount_nearby_curvature():
    lats, lngs = twisty_road()
    mask = no_junctions(len(lats))
    clean, _, _ = curvature_score(lats, lngs, mask, CFG)
    all_junctions = np.ones(len(lats), dtype=bool)  # driveway hell
    discounted, _, _ = curvature_score(lats, lngs, all_junctions, CFG)
    # every vertex sits in a conflict zone, so the whole way is discounted —
    # heavily penalized (guardrail 4) but no longer erased outright.
    assert discounted == pytest.approx(clean * CFG["conflict_points"]["near_junction_weight"])
    assert 0 < discounted < clean


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
    mask = through_road(len(lats))
    paved = score_way({"highway": "tertiary", "surface": "asphalt"}, lats, lngs, mask, None, CFG)
    gravel = score_way({"highway": "tertiary", "surface": "gravel"}, lats, lngs, mask, None, CFG)
    assert paved["fun_index"] > 0.3
    assert gravel["fun_index"] < 0.05


def test_low_limit_tight_geometry_penalized():
    lats, lngs = twisty_road()
    mask = through_road(len(lats))
    open_road = score_way({"highway": "tertiary"}, lats, lngs, mask, None, CFG)
    goat_path = score_way({"highway": "tertiary", "maxspeed": "25 mph"}, lats, lngs, mask, None, CFG)
    assert goat_path["fun_index"] < open_road["fun_index"]


def test_unknown_highway_skipped():
    lats, lngs = straight_road()
    assert score_way({"highway": "bridleway"}, lats, lngs, no_junctions(len(lats)), None, CFG) is None


def test_residential_open_qualifies_slow_low_density_street():
    lats, lngs = twisty_road()
    mask = through_road(len(lats))  # zero INTERIOR junction density
    default_residential = score_way({"highway": "residential"}, lats, lngs, mask, None, CFG)
    open_residential = score_way(
        {"highway": "residential", "maxspeed": "25 mph"}, lats, lngs, mask, None, CFG
    )
    # no maxspeed tag also qualifies (unsigned US residential default 25 mph)
    assert default_residential["fun_index"] == open_residential["fun_index"]
    assert default_residential["components"]["road_class"] == CFG["road_class"]["residential_open"]


def test_residential_stays_suppressed_above_speed_threshold():
    lats, lngs = twisty_road()
    mask = through_road(len(lats))
    fast = score_way({"highway": "residential", "maxspeed": "45 mph"}, lats, lngs, mask, None, CFG)
    assert fast["components"]["road_class"] == CFG["road_class"]["residential"]


def test_residential_stays_suppressed_at_high_junction_density():
    lats, lngs = twisty_road()
    dense = np.ones(len(lats), dtype=bool)  # a junction at every vertex
    busy = score_way({"highway": "residential", "maxspeed": "25 mph"}, lats, lngs, dense, None, CFG)
    assert busy["components"]["road_class"] == CFG["road_class"]["residential"]


def test_cul_de_sac_is_not_a_fun_road():
    # A dead-end court: curvy, slow, zero interior junctions — it used to
    # sail past every gate and rank among the best roads in the state.
    lats, lngs = twisty_road()
    dead_end = no_junctions(len(lats))
    dead_end[0] = True  # joins the network at one end only
    scored = score_way(
        {"highway": "residential", "maxspeed": "25 mph"}, lats, lngs, dead_end, None, CFG
    )
    assert scored["components"]["road_class"] == CFG["road_class"]["dead_end"]
    # must fall below the bar for being hunted as a standout road, or
    # peak-seeking will route people into a cul-de-sac and back out again
    assert scored["fun_index"] < CFG["seek"]["min_fun_index"]


def test_dead_end_override_beats_the_residential_promotion():
    lats, lngs = twisty_road()
    promoted = score_way(
        {"highway": "residential", "maxspeed": "25 mph"},
        lats, lngs, through_road(len(lats)), None, CFG,
    )
    stub = score_way(
        {"highway": "residential", "maxspeed": "25 mph"},
        lats, lngs, no_junctions(len(lats)), None, CFG,
    )
    assert promoted["components"]["road_class"] == CFG["road_class"]["residential_open"]
    assert stub["components"]["road_class"] == CFG["road_class"]["dead_end"]
    assert stub["fun_index"] < promoted["fun_index"]


def test_a_parking_lot_is_never_a_fun_road():
    """The reported defect. Aisle geometry is nothing but tight corners, so a
    service way saturates the 0.60-weighted curvature term; with road class as
    a 0.25-weighted blend component, `service: 0.0` could only dock a quarter
    of that and the lot still came out at 0.755. Measured consequence: 219,383
    of the 278,965 ways in the seek index (79%) were service road, and a real
    route drove 2,554 m of parking lot."""
    lats, lngs = twisty_road()
    mask = through_road(len(lats))
    road = score_way({"highway": "tertiary"}, lats, lngs, mask, None, CFG)
    parking_lot = score_way({"highway": "service"}, lats, lngs, mask, None, CFG)
    # identical geometry — class alone must be able to sink it
    assert road["components"]["curvature"] == parking_lot["components"]["curvature"]
    assert parking_lot["fun_index"] < CFG["seek"]["min_fun_index"]
    # and below the bottom routing tier, so the fun dial won't dive into one
    assert parking_lot["fun_index"] < CFG["gh_custom_model"]["priority"][0]["factor"]


def test_the_class_gate_cannot_be_outrun_by_perfect_geometry():
    """A veto, not a haircut: no amount of curvature or elevation rescues a
    class that isn't a road you drive for pleasure."""
    lats, lngs = twisty_road()
    mask = through_road(len(lats))
    for highway in ("service", "living_street"):
        scored = score_way({"highway": highway, "surface": "asphalt"},
                           lats, lngs, mask, None, CFG)
        ungated = (
            CFG["blend"]["curvature"] * scored["components"]["curvature"]
            + CFG["blend"]["elevation"] * scored["components"]["elevation"]
            + CFG["blend"]["road_class"] * scored["components"]["road_class"]
        )
        assert scored["gates"]["road_class"] == CFG["road_class"]["gate"][highway]
        assert scored["fun_index"] < ungated * 0.2


def test_a_dead_end_is_gated_whatever_its_class():
    """`dead_end` is documented as an override that beats every promotion, and
    as a blend component it could not be one: at 0.02 it scored a service way
    *higher* than `service: 0.0` did, which is why the very top of the seek
    index was dead-end driveways at exactly 0.755."""
    lats, lngs = twisty_road()
    stub = no_junctions(len(lats))
    stub[0] = True  # joins the network at one end only
    for highway in ("tertiary", "unclassified", "residential"):
        scored = score_way({"highway": highway}, lats, lngs, stub, None, CFG)
        assert scored["gates"]["road_class"] == CFG["road_class"]["gate"]["dead_end"]
        assert scored["fun_index"] < CFG["seek"]["min_fun_index"]


def test_ordinary_road_classes_are_not_gated():
    """The gate is a targeted veto, not a general suppressant — it must leave
    the classes the app exists to find completely alone."""
    lats, lngs = twisty_road()
    mask = through_road(len(lats))
    for highway in ("tertiary", "unclassified", "secondary", "primary"):
        scored = score_way({"highway": highway}, lats, lngs, mask, None, CFG)
        assert scored["gates"]["road_class"] == 1.0
    assert score_way({"highway": "tertiary"}, lats, lngs, mask, None, CFG)["fun_index"] > 0.3


def test_through_tertiary_is_unaffected_by_the_dead_end_rule():
    lats, lngs = twisty_road()
    scored = score_way({"highway": "tertiary"}, lats, lngs, through_road(len(lats)), None, CFG)
    assert scored["components"]["road_class"] == CFG["road_class"]["tertiary"]


def test_endpoint_junctions_alone_do_not_count_as_access_density():
    # OSM splits ways AT intersections, so both endpoints are junctions by
    # construction — that must not read as a driveway-dense road.
    lats, lngs = twisty_road()
    ends_only = no_junctions(len(lats))
    ends_only[0] = ends_only[-1] = True
    scored = score_way({"highway": "tertiary"}, lats, lngs, ends_only, None, CFG)
    assert scored["gates"]["safety"] == 1.0


def test_residential_open_still_subject_to_goat_path_safety_gate():
    # Promotion to residential_open must not bypass the existing tight-curve
    # -at-low-limit safety gate (guardrail 4) — it only affects road_class.
    lats, lngs = twisty_road()
    mask = through_road(len(lats))
    open_tertiary = score_way({"highway": "tertiary"}, lats, lngs, mask, None, CFG)
    open_residential = score_way(
        {"highway": "residential", "maxspeed": "25 mph"}, lats, lngs, mask, None, CFG
    )
    assert open_residential["components"]["road_class"] == CFG["road_class"]["residential_open"]
    assert open_residential["gates"]["safety"] < 1.0  # goat-path gate still fired


def test_motorway_scores_below_tertiary():
    lats, lngs = twisty_road()
    mask = through_road(len(lats))
    tertiary = score_way({"highway": "tertiary", "surface": "asphalt"}, lats, lngs, mask, None, CFG)
    motorway = score_way({"highway": "motorway", "surface": "asphalt"}, lats, lngs, mask, None, CFG)
    assert motorway["fun_index"] < tertiary["fun_index"]