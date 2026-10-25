"""Out-and-back detection — the "route nobody would drive" defect.

Measured on real routes before the fix: every seek candidate re-drove road
(up to 9.1 km of a 74 km route) while no plain fun-dial candidate re-drove
any, and all three generated drive loops re-drove 5-7.6%.
"""
import pytest

from app.overlap import retraversal_penalty_s, retraversed_m

# ~1 km apart at Michigan latitudes, as [lng, lat] like GraphHopper returns.
A = [-85.6000, 42.9000]
B = [-85.6000, 42.9090]
C = [-85.6000, 42.9180]
D = [-85.5890, 42.9180]


def test_a_route_that_never_repeats_scores_zero():
    assert retraversed_m([A, B, C, D]) == 0.0


def test_an_out_and_back_counts_the_road_once():
    # up to C and straight back down: B→C is the doubled stretch
    out_and_back = [A, B, C, B, A]
    one_way = retraversed_m([A, B, C])
    assert one_way == 0.0
    # the return leg re-drives both B→C and A→B
    doubled = retraversed_m(out_and_back)
    assert doubled == pytest.approx(2000, abs=60)


def test_direction_does_not_matter():
    """Driving a road out and back traverses each edge once per direction —
    counting directed edges would score that as zero repeats."""
    assert retraversed_m([A, B, A]) > 0


def test_a_spur_off_an_otherwise_clean_route():
    # A→B→C, detour up to D and back, then on — only B↔D is doubled
    spur = [A, B, D, B, C]
    assert retraversed_m(spur) == pytest.approx(retraversed_m([B, D, B]))


def test_a_stretch_driven_three_times_counts_twice():
    assert retraversed_m([A, B, A, B]) == pytest.approx(2 * retraversed_m([A, B, A]))


def test_a_loop_touching_one_point_twice_is_not_a_retraversal():
    """A figure-eight shares a *node*, not an edge — that's a legitimate loop
    and must not be penalised as doubling back."""
    assert retraversed_m([A, B, C, D, B]) == 0.0


def test_penalty_scales_with_road_redriven():
    one_km_doubled = [A, B, A]
    assert retraversal_penalty_s(one_km_doubled, minutes_per_km=30) == pytest.approx(
        retraversed_m(one_km_doubled) / 1000.0 * 30 * 60
    )


def test_penalty_is_zero_for_a_clean_route():
    assert retraversal_penalty_s([A, B, C, D], minutes_per_km=30) == 0.0


def test_short_routes_do_not_blow_up():
    assert retraversed_m([]) == 0.0
    assert retraversed_m([A]) == 0.0


# --- the flat charge -------------------------------------------------------
# What reached a user was a 122 m overshoot that turned around: trivial by
# distance, glaring on the map. Distance alone can't price that.

# ~122 m north of A, the measured overshoot on the reported route.
OVERSHOOT = [-85.6000, 42.9011]


def test_a_short_double_back_is_charged_far_more_than_its_length():
    tiny = [A, OVERSHOOT, A]
    per_km_only = retraversal_penalty_s(tiny, minutes_per_km=30)
    with_flat = retraversal_penalty_s(
        tiny, minutes_per_km=30, fixed_minutes=20, ignore_m=25
    )
    # the whole point: ~3.7 min of distance, which a 25 min budget waves through
    assert per_km_only == pytest.approx(3.7 * 60, abs=30)
    assert with_flat == pytest.approx(per_km_only + 20 * 60)
    # with the detour's own +3.4 min on top (the measured figure for the route
    # that reached a user): comfortably inside a 25 min budget before, over it
    # after. That flip is the whole fix.
    detour_s = 3.4 * 60
    assert detour_s + per_km_only < 25 * 60
    assert detour_s + with_flat > 25 * 60


def test_the_flat_charge_is_the_same_however_long_the_double_back():
    """It prices the fact that it happened. The per-km term prices the rest."""
    short = retraversal_penalty_s([A, OVERSHOOT, A], 30, fixed_minutes=20, ignore_m=25)
    long = retraversal_penalty_s([A, C, A], 30, fixed_minutes=20, ignore_m=25)
    assert retraversed_m([A, C, A]) > 10 * retraversed_m([A, OVERSHOOT, A])
    assert long - short == pytest.approx(
        retraversal_penalty_s([A, C, A], 30) - retraversal_penalty_s([A, OVERSHOOT, A], 30)
    )


def test_a_clean_route_is_charged_nothing_at_all():
    """Every good seek candidate measured across seven real routes re-drove
    exactly 0 m, so the flat charge must never touch them."""
    assert retraversal_penalty_s(
        [A, B, C, D], minutes_per_km=30, fixed_minutes=20, ignore_m=25
    ) == 0.0


def test_a_stray_metre_at_a_junction_does_not_trigger_the_flat_charge():
    """Shared geometry where two ways meet is not doubling back — without the
    tolerance it would cost a full 20 min."""
    nudge = [-85.6000, 42.90005]  # ~5 m, well under ignore_m
    assert 0 < retraversed_m([A, nudge, A]) < 25
    assert retraversal_penalty_s(
        [A, nudge, A], minutes_per_km=30, fixed_minutes=20, ignore_m=25
    ) == 0.0


def test_the_flat_charge_is_off_by_default():
    """The drive-loop caller passes only a rate — a loop coming home past a
    road it already drove is far less objectionable than an A→B route doing
    it, and must keep its existing pricing."""
    doubled = [A, B, A]
    assert retraversal_penalty_s(doubled, minutes_per_km=12) == pytest.approx(
        retraversed_m(doubled) / 1000.0 * 12 * 60
    )
