from app.funindex import summarize_route

# Two equal-length legs of a west-east line at 42°N (~0.01° ≈ 826 m each).
COORDS = [[-84.00, 42.0], [-83.99, 42.0], [-83.98, 42.0]]
INTERVALS = [[0, 1, 111], [1, 2, 222]]


def doc(fun, curv, elev, rc, surface=1.0, safety=1.0, name=None):
    return {
        "fun_index": fun,
        "name": name,
        "components": {"curvature": curv, "elevation": elev, "road_class": rc},
        "gates": {"surface": surface, "safety": safety},
    }


def test_breakdown_is_length_weighted_across_the_route():
    docs = {
        111: doc(0.80, 1.0, 0.6, 1.00),
        222: doc(0.20, 0.0, 0.2, 0.05),
    }
    fun, why = summarize_route(COORDS, INTERVALS, docs, default_fun=0.25)

    # equal legs → plain average of both ways
    assert fun == 0.5
    assert why["curvature"] == 0.5
    assert why["elevation"] == 0.4
    assert why["road_class"] == 0.525
    assert why["scored_fraction"] == 1.0


def test_gates_surface_through_and_default_to_unpenalized():
    docs = {
        111: doc(0.02, 0.5, 0.5, 1.0, surface=0.02),  # gravel
        222: {"fun_index": 0.5, "components": {"curvature": 0.5}},  # gates absent
    }
    _, why = summarize_route(COORDS, INTERVALS, docs, default_fun=0.25)

    assert why["surface"] == 0.51  # (0.02 + 1.0) / 2 — missing gate = no penalty
    assert why["safety"] == 1.0
    # a component missing from the doc counts as zero contribution
    assert why["elevation"] == 0.25


def test_safety_gate_penalty_is_visible():
    docs = {111: doc(0.3, 0.9, 0.2, 0.75, safety=0.5), 222: doc(0.4, 0.9, 0.2, 0.75)}
    _, why = summarize_route(COORDS, INTERVALS, docs, default_fun=0.25)
    assert why["safety"] == 0.75  # (0.5 + 1.0) / 2 — the goat-path gate shows up


def test_unscored_ways_dilute_fun_but_not_the_breakdown():
    docs = {111: doc(0.9, 1.0, 1.0, 1.0)}  # way 222 unknown
    fun, why = summarize_route(COORDS, INTERVALS, docs, default_fun=0.25)

    assert fun == 0.575  # (0.9 + 0.25 default) / 2
    # breakdown reflects only the scored half, and says so
    assert why["curvature"] == 1.0
    assert why["scored_fraction"] == 0.5


def test_couch_unavailable_yields_no_numbers():
    assert summarize_route(COORDS, INTERVALS, None, 0.25) == (None, None)


def test_no_scored_segments_keeps_fun_but_drops_breakdown():
    fun, why = summarize_route(COORDS, INTERVALS, {}, default_fun=0.25)
    assert fun == 0.25
    assert why is None


def test_repeated_intervals_of_one_way_count_once_by_total_length():
    # GraphHopper can split a single way across intervals; the way must not be
    # over-weighted just for appearing twice.
    split = [[0, 1, 111], [1, 2, 111]]
    fun, why = summarize_route(COORDS, split, {111: doc(0.7, 0.8, 0.4, 0.9)}, 0.25)
    assert fun == 0.7
    assert why["curvature"] == 0.8
