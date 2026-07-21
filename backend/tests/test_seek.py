import pytest

from app.schemas import LatLng
from app.seek import corridor_cells, earned_detour_s, rank_targets, target_value

CFG = {
    "cell_size_deg": 0.02,
    "corridor_buffer_km": 6,
    "min_length_m": 150,
    "max_targets": 3,
    "exclude_highways": ["residential", "living_street", "service"],
    "length_cap_m": 3000,
    "corridor_half_km": 3.0,
    "detour_minutes_per_km": 12,
}

# Grand Rapids → south, roughly the reported Hall St corridor.
ORIGIN = LatLng(lat=43.0097, lng=-85.6590)
DEST = LatLng(lat=42.5430, lng=-85.8472)


def row(fun, lat, lng, name, length_m=300.0, highway="tertiary"):
    return {
        "value": {
            "fun": fun,
            "mid": [lat, lng],
            "name": name,
            "length_m": length_m,
            "highway": highway,
        }
    }


def test_corridor_cells_cover_both_endpoints():
    cells = corridor_cells(ORIGIN, DEST, 0.02, 6)
    assert [int(ORIGIN.lat // 0.02), int(ORIGIN.lng // 0.02)] in cells
    assert [int(DEST.lat // 0.02), int(DEST.lng // 0.02)] in cells
    # a corridor this long must not explode into an unbounded key list
    assert len(cells) < 5000


def test_best_road_ranks_first():
    rows = [
        row(0.45, 42.80, -85.75, "Decent Rd"),
        row(0.72, 42.90, -85.72, "Great Curve"),
        row(0.50, 42.70, -85.78, "Okay Rd"),
    ]
    targets = rank_targets(rows, ORIGIN, DEST, CFG)
    assert targets[0]["name"] == "Great Curve"
    assert targets[0]["fun_index"] == 0.72


def test_a_long_road_on_the_way_beats_a_short_gem_far_off_it():
    # exactly the failure that made seek offer +35 min for 902 m of road
    rows = [
        row(0.95, 42.905, -85.716, "Short Gem", length_m=260.0),
        row(0.88, 42.83, -85.762, "Long Good Road", length_m=1800.0),
    ]
    names = [t["name"] for t in rank_targets(rows, ORIGIN, DEST, CFG)]
    assert names[0] == "Long Good Road"


def test_length_stops_multiplying_past_the_cap():
    near = {"fun_index": 0.8, "length_m": 3000.0, "off_corridor_km": 0.0}
    huge = {"fun_index": 0.8, "length_m": 30000.0, "off_corridor_km": 0.0}
    assert target_value(huge, CFG) == target_value(near, CFG)


def test_value_halves_at_the_corridor_half_distance():
    on_line = {"fun_index": 0.9, "length_m": 800.0, "off_corridor_km": 0.0}
    off_line = {"fun_index": 0.9, "length_m": 800.0, "off_corridor_km": CFG["corridor_half_km"]}
    assert target_value(off_line, CFG) == pytest.approx(target_value(on_line, CFG) / 2)


def test_a_detour_must_be_earned_by_the_road():
    # 902 m at 0.93 fun buys ~10 min, nowhere near the +35 min that prompted this
    target = {"fun_index": 0.93, "length_m": 902.0, "off_corridor_km": 2.4}
    earned = earned_detour_s(target, CFG)
    assert earned == pytest.approx(12 * 0.902 * 0.93 * 60, rel=1e-6)
    assert earned < 35 * 60
    assert earned > 8 * 60


def test_a_longer_better_road_earns_a_longer_detour():
    short = {"fun_index": 0.9, "length_m": 400.0, "off_corridor_km": 0.0}
    long = {"fun_index": 0.9, "length_m": 2000.0, "off_corridor_km": 0.0}
    assert earned_detour_s(long, CFG) > earned_detour_s(short, CFG)


def test_roads_far_off_the_corridor_are_dropped():
    # ~100 km east of the corridor
    rows = [row(0.9, 42.80, -84.40, "Far Away Rd")]
    assert rank_targets(rows, ORIGIN, DEST, CFG) == []


def test_subdivision_streets_are_never_sought():
    # Regal Drive, measured: curvature and elevation both maxed, no gate fires,
    # scores 0.938 — geometry alone can't tell it's someone's neighbourhood.
    # Seeking means detouring *to* a road, which this never warrants.
    rows = [
        row(0.94, 42.90, -85.72, "Regal Drive", length_m=478.0, highway="residential"),
        row(0.61, 42.88, -85.73, "Real Road", highway="tertiary"),
    ]
    targets = rank_targets(rows, ORIGIN, DEST, CFG)
    assert [t["name"] for t in targets] == ["Real Road"]


def test_excluding_seek_targets_does_not_touch_their_score():
    # they stay routable and scored — only the "go out of your way" list is
    # filtered, so a curvy residential street on your way is still preferred
    rows = [row(0.94, 42.90, -85.72, "Regal Drive", length_m=478.0, highway="residential")]
    assert rank_targets(rows, ORIGIN, DEST, CFG) == []
    assert rows[0]["value"]["fun"] == 0.94


def test_slivers_are_dropped():
    rows = [row(0.95, 42.90, -85.72, "Tiny Sliver", length_m=80.0)]
    assert rank_targets(rows, ORIGIN, DEST, CFG) == []


def test_adjacent_slices_of_one_road_collapse_to_one_target():
    # OSM splits a road into many ways; three slices of the same curve should
    # not consume all three routing attempts.
    rows = [
        row(0.70, 42.9000, -85.7200, "Hall Street SW"),
        row(0.68, 42.9010, -85.7205, "Hall Street SW"),
        row(0.66, 42.9020, -85.7210, "Hall Street SW"),
        row(0.60, 42.7500, -85.7800, "Other Rd"),
    ]
    targets = rank_targets(rows, ORIGIN, DEST, CFG)
    assert len(targets) == 2
    assert targets[0]["name"] == "Hall Street SW"
    assert targets[1]["name"] == "Other Rd"


def test_respects_max_targets():
    rows = [row(0.9 - i * 0.01, 42.60 + i * 0.05, -85.80, f"Rd {i}") for i in range(10)]
    assert len(rank_targets(rows, ORIGIN, DEST, CFG)) == CFG["max_targets"]


def test_off_corridor_distance_is_reported():
    targets = rank_targets([row(0.7, 42.90, -85.72, "Near Rd")], ORIGIN, DEST, CFG)
    assert 0 <= targets[0]["off_corridor_km"] <= CFG["corridor_buffer_km"]
