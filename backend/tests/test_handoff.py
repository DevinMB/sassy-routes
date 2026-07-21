import httpx
import pytest
import respx

from app.deeplink import maps_deep_link
from app.verify import HandoffVerifier, decode_polyline
from app.waypoints import compress

MAX_WP = 9
MAX_EXCESS = 400.0

# ---------------------------------------------------------------- compression


def straight(n=30):
    return [[-84.0 + i * 0.002, 42.0] for i in range(n)]


def gentle_freeway_curve():
    """Long arc — big corridor sag from the chord, near-zero excess length.
    Must NOT trigger waypoints: the sag is the road, Google follows it."""
    import math
    pts = []
    for i in range(41):
        t = i / 40
        pts.append([-84.0 + t * 0.5, 42.0 + 0.03 * math.sin(math.pi * t)])
    return pts


def single_detour():
    """West-east line with one ~2.2 km northward spike Google would cut."""
    return [
        [-84.00, 42.0], [-83.98, 42.0], [-83.96, 42.02],
        [-83.94, 42.0], [-83.90, 42.0],
    ]


def sawtooth(teeth=15, amplitude=0.01):
    """More independent detours than the waypoint budget can pin."""
    pts = []
    for i in range(teeth * 2 + 1):
        pts.append([-84.0 + i * 0.01, 42.0 + (amplitude if i % 2 else 0.0)])
    return pts


def test_straight_route_needs_no_waypoints():
    idxs, excess, pinned = compress(straight(), MAX_WP, MAX_EXCESS)
    assert idxs == []
    assert excess < 1.0
    assert pinned


def test_smooth_curve_is_not_mistaken_for_detour():
    # ~3 km max sag from the chord, but the path barely exceeds the chord —
    # the exact failure mode of corridor-deviation metrics.
    idxs, excess, pinned = compress(gentle_freeway_curve(), MAX_WP, MAX_EXCESS)
    assert pinned
    assert len(idxs) <= 1


def test_detour_apex_becomes_waypoint():
    coords = single_detour()
    idxs, excess, pinned = compress(coords, MAX_WP, MAX_EXCESS)
    assert pinned
    assert 2 in idxs  # the spike apex — exactly where Google would shortcut
    assert excess <= MAX_EXCESS


def test_waypoint_budget_exhaustion_reports_unpinned():
    idxs, excess, pinned = compress(sawtooth(), MAX_WP, MAX_EXCESS)
    assert len(idxs) == MAX_WP
    assert not pinned
    assert excess > MAX_EXCESS  # honest: never silently emit a broken link


def test_two_point_route_trivially_pinned():
    idxs, excess, pinned = compress([[-84.0, 42.0], [-83.9, 42.1]], MAX_WP, MAX_EXCESS)
    assert idxs == [] and pinned


# ------------------------------------------------------------------ deep link


def test_deep_link_format():
    coords = single_detour()
    url = maps_deep_link(coords, [2])
    assert url.startswith("https://www.google.com/maps/dir/?api=1")
    assert "origin=42.000000,-84.000000" in url
    assert "destination=42.000000,-83.900000" in url
    assert "waypoints=42.020000,-83.960000" in url
    assert "travelmode=driving" in url


def test_deep_link_multiple_waypoints_pipe_separated():
    url = maps_deep_link(single_detour(), [1, 2, 3])
    assert url.count("|") == 2


# ------------------------------------------------------------- verified mode


def encode_polyline(coords):
    """Inverse of decode_polyline, for test fixtures ([lng,lat] input)."""
    out, prev_lat, prev_lng = [], 0, 0
    for lng, lat in coords:
        for value, prev in ((round(lat * 1e5), prev_lat), (round(lng * 1e5), prev_lng)):
            delta = value - prev
            v = ~(delta << 1) if delta < 0 else delta << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        prev_lat, prev_lng = round(lat * 1e5), round(lng * 1e5)
    return "".join(out)


def test_decode_polyline_google_reference_vector():
    decoded = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert decoded[0] == pytest.approx([-120.2, 38.5])
    assert decoded[1] == pytest.approx([-120.95, 40.7])
    assert decoded[2] == pytest.approx([-126.453, 43.252])


def test_encode_decode_roundtrip():
    coords = single_detour()
    decoded = decode_polyline(encode_polyline(coords))
    assert len(decoded) == len(coords)
    for got, want in zip(decoded, coords):
        assert got == pytest.approx(want, abs=1e-5)


def big_detour():
    return single_detour()  # ~2.2 km apex


def directions_json(coords):
    return {
        "status": "OK",
        "routes": [{"overview_polyline": {"points": encode_polyline(coords)}}],
    }


@respx.mock
def test_verifier_inserts_waypoint_then_confirms():
    ours = big_detour()
    shortcut = [ours[0], ours[-1]]  # Google ignores the detour at first
    route = respx.get("https://maps.googleapis.com/maps/api/directions/json").mock(
        side_effect=[
            httpx.Response(200, json=directions_json(shortcut)),
            httpx.Response(200, json=directions_json(ours)),
        ]
    )
    verifier = HandoffVerifier("test-key")
    idxs, verified = verifier.verify(ours, [], MAX_WP, 250.0, 3)
    assert verified
    assert idxs, "a pinning waypoint should have been inserted"
    assert route.call_count == 2
    # second call must carry a via: waypoint
    assert "via%3A" in str(route.calls[1].request.url)


@respx.mock
def test_verifier_gives_up_gracefully_on_api_error():
    respx.get("https://maps.googleapis.com/maps/api/directions/json").mock(
        return_value=httpx.Response(200, json={"status": "OVER_QUERY_LIMIT"})
    )
    idxs, verified = HandoffVerifier("test-key").verify(big_detour(), [1], MAX_WP, 250.0, 3)
    assert not verified
    assert idxs == [1]  # unchanged — best-effort link still ships
