import math

from app.grid import aggregate, bbox_cells

CELL = 0.02


def cell_of(lat, lng):
    return [math.floor(lat / CELL), math.floor(lng / CELL)]


def test_bbox_cells_cover_the_viewport():
    # interior coords, to avoid float ambiguity right on cell edges
    cells = bbox_cells(42.011, -84.991, 42.049, -84.951, CELL, max_cells=4000)
    assert cell_of(42.011, -84.991) in cells
    assert cell_of(42.049, -84.951) in cells
    # spans 3 cells of latitude (42.00-.02-.04) x 3 of longitude
    assert len(cells) == 9


def test_bbox_cells_refuses_a_viewport_thats_too_broad():
    # whole lower peninsula at 0.02° cells is way over the cap
    assert bbox_cells(41.7, -87.0, 45.9, -82.4, CELL, max_cells=4000) == []


def test_bbox_cells_handles_inverted_corners():
    a = bbox_cells(42.05, -84.95, 42.00, -85.00, CELL, max_cells=4000)
    b = bbox_cells(42.00, -85.00, 42.05, -84.95, CELL, max_cells=4000)
    assert sorted(a) == sorted(b)


def test_aggregate_sums_fun_times_length_per_cell():
    rows = [
        {"key": [2100, -4250], "value": {"fun": 0.8, "length_m": 1000}},
        {"key": [2100, -4250], "value": {"fun": 0.5, "length_m": 400}},  # same cell
        {"key": [2101, -4250], "value": {"fun": 0.9, "length_m": 500}},
    ]
    tiles = {(t["lat"], t["lng"]): t["weight"] for t in aggregate(rows, CELL)}
    assert len(tiles) == 2
    # first cell: 0.8*1000 + 0.5*400 = 1000
    centre = (round((2100 + 0.5) * CELL, 6), round((-4250 + 0.5) * CELL, 6))
    assert tiles[centre] == 1000.0


def test_aggregate_skips_zero_and_missing():
    rows = [
        {"key": [1, 1], "value": {"fun": 0.0, "length_m": 900}},  # zero fun
        {"value": {"fun": 0.9, "length_m": 900}},  # no key
        {"key": [1, 1]},  # no value
    ]
    assert aggregate(rows, CELL) == []
