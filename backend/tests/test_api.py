import json

import httpx
import respx
from fastapi.testclient import TestClient

from app.main import _cache_key, app
from app.schemas import LatLng
from app.scoring import scoring

client = TestClient(app)
GH = "http://graphhopper:8989"
COUCH = "http://couch.test:5984"

ANN_ARBOR = {"lat": 42.281, "lng": -83.743}
DETROIT = {"lat": 42.331, "lng": -83.046}
DENVER = {"lat": 39.739, "lng": -104.990}


def gh_path(distance, time_ms, coords, way_intervals):
    return {
        "paths": [{
            "distance": distance,
            "time": time_ms,
            "points": {"type": "LineString", "coordinates": coords},
            "details": {"osm_way_id": way_intervals},
        }]
    }


COORDS_FAST = [[-83.743, 42.281], [-83.4, 42.3], [-83.046, 42.331]]
COORDS_FUN = [[-84.0, 42.0], [-84.0, 42.01], [-84.0, 42.02]]

FASTEST_MS = 600_000
# Derived from the real config so tuning max_time_multiplier can't silently
# turn the over-budget fixture into an in-budget one.
OVER_BUDGET_MS = int(FASTEST_MS * scoring()["routing"]["max_time_multiplier"]) + 60_000

FASTEST = gh_path(10000, FASTEST_MS, COORDS_FAST, [[0, 2, 111]])
NEAR_DUPLICATE = gh_path(10050, 605_000, COORDS_FAST, [[0, 2, 111]])  # λ=0.3
FUN_ROUTE = gh_path(12000, 900_000, COORDS_FUN, [[0, 1, 222], [1, 2, 333]])  # λ=0.6
TOO_SLOW = gh_path(30000, OVER_BUDGET_MS, COORDS_FUN, [[0, 2, 222]])  # λ=0.9: over cap


def mock_couch(segment_rows=None, cache_hit=None):
    key = _cache_key(LatLng(**ANN_ARBOR), LatLng(**DETROIT), __import__("app.scoring", fromlist=["scoring"]).scoring())
    if cache_hit is not None:
        respx.get(f"{COUCH}/route_cache/{key}").mock(
            return_value=httpx.Response(200, json=cache_hit)
        )
    else:
        respx.get(f"{COUCH}/route_cache/{key}").mock(return_value=httpx.Response(404))
    respx.put(f"{COUCH}/route_cache").mock(return_value=httpx.Response(412))
    respx.put(f"{COUCH}/route_cache/{key}").mock(return_value=httpx.Response(201))
    respx.post(f"{COUCH}/segments/_all_docs").mock(
        return_value=httpx.Response(200, json={"rows": segment_rows or []})
    )
    return key


SEGMENT_ROWS = [
    {"key": "way:111", "doc": {"fun_index": 0.2}},
    {"key": "way:222", "doc": {"fun_index": 0.8}},
    {"key": "way:333", "error": "not_found"},  # unscored → default_fun 0.25
]


@respx.mock
def test_route_returns_deduped_capped_candidates():
    respx.get(f"{GH}/route").mock(return_value=httpx.Response(200, json=FASTEST))
    post_route = respx.post(f"{GH}/route").mock(
        side_effect=[
            httpx.Response(200, json=NEAR_DUPLICATE),
            httpx.Response(200, json=FUN_ROUTE),
            httpx.Response(200, json=TOO_SLOW),
        ]
    )
    mock_couch(SEGMENT_ROWS)

    resp = client.post("/api/route", json={"origin": ANN_ARBOR, "destination": DETROIT})
    assert resp.status_code == 200
    cands = resp.json()["candidates"]

    # fastest + λ=0.6 survive; λ=0.3 deduped, λ=0.9 capped
    assert [c["fun_dial"] for c in cands] == [0.0, 0.6]
    fastest, fun = cands
    assert fastest["dtime_s"] == 0.0
    assert fastest["fun_index"] == 0.2
    assert fun["dtime_s"] == 300.0
    # equal-length intervals: (0.8 + 0.25) / 2
    assert fun["fun_index"] == 0.525

    # custom models scale with λ and only ever penalize (multiply_by ≤ 1)
    first_model = json.loads(post_route.calls[0].request.content)["custom_model"]
    assert all(rule["multiply_by"] <= 1.0 for rule in first_model["priority"])

    # every candidate carries a Maps handoff
    for c in cands:
        assert c["handoff"]["maps_url"].startswith("https://www.google.com/maps/dir/?api=1")
        assert c["handoff"]["pinned"] is True
        assert c["handoff"]["verified"] is False  # verify flag is off by default
    # fastest hands off waypoint-free: Google optimizes the same objective
    assert fastest["handoff"]["waypoints_used"] == 0
    assert "waypoints" not in fastest["handoff"]["maps_url"]


@respx.mock
def test_peak_seeking_adds_a_candidate_through_a_standout_road():
    respx.get(f"{GH}/route").mock(return_value=httpx.Response(200, json=FASTEST))
    # λ candidates all duplicate the fastest; only the via-routed one differs
    post_route = respx.post(f"{GH}/route").mock(
        side_effect=[
            httpx.Response(200, json=NEAR_DUPLICATE),
            httpx.Response(200, json=NEAR_DUPLICATE),
            httpx.Response(200, json=NEAR_DUPLICATE),
            httpx.Response(200, json=FUN_ROUTE),  # the seek attempt
        ]
    )
    mock_couch(SEGMENT_ROWS)
    respx.post(f"{COUCH}/segments/_design/seek/_view/by_cell").mock(
        return_value=httpx.Response(200, json={"rows": [{
            # long and good enough to earn the fixture's 5 min detour
            "value": {
                "fun": 0.80, "mid": [42.30, -83.40], "highway": "tertiary",
                "name": "Hall Street SW", "length_m": 1800.0,
            }
        }]})
    )

    resp = client.post("/api/route", json={"origin": ANN_ARBOR, "destination": DETROIT})
    assert resp.status_code == 200
    sought = [c for c in resp.json()["candidates"] if c["sought"]]
    assert len(sought) == 1
    assert sought[0]["sought"]["name"] == "Hall Street SW"
    assert sought[0]["sought"]["fun_index"] == 0.80
    # the seek request must actually pin the via-point
    body = json.loads(post_route.calls[-1].request.content)
    assert len(body["points"]) == 3
    assert body["points"][1] == [-83.40, 42.30]


@respx.mock
def test_seek_declines_a_detour_the_road_does_not_earn():
    # A short road can't justify a long detour beyond what the fun route
    # already costs — the extra 10 min here buys 261 m, which earns ~1.8 min.
    slow_seek = gh_path(30000, 1_500_000, COORDS_FUN, [[0, 2, 222]])
    respx.get(f"{GH}/route").mock(return_value=httpx.Response(200, json=FASTEST))
    respx.post(f"{GH}/route").mock(
        side_effect=[
            httpx.Response(200, json=FUN_ROUTE),  # λ=0.3 → kept, 900s baseline
            httpx.Response(200, json=FUN_ROUTE),  # λ=0.6 → deduped
            httpx.Response(200, json=FUN_ROUTE),  # λ=0.9 → deduped
            httpx.Response(200, json=slow_seek),  # seek attempt: +10 min
        ]
    )
    mock_couch(SEGMENT_ROWS)
    respx.post(f"{COUCH}/segments/_design/seek/_view/by_cell").mock(
        return_value=httpx.Response(200, json={"rows": [{
            "value": {
                "fun": 0.57, "mid": [42.30, -83.40], "highway": "tertiary",
                "name": "Brief Curve", "length_m": 261.0,
            }
        }]})
    )
    resp = client.post("/api/route", json={"origin": ANN_ARBOR, "destination": DETROIT})
    assert resp.status_code == 200
    assert all(c["sought"] is None for c in resp.json()["candidates"])


@respx.mock
def test_seek_view_missing_does_not_break_routing():
    respx.get(f"{GH}/route").mock(return_value=httpx.Response(200, json=FASTEST))
    respx.post(f"{GH}/route").mock(return_value=httpx.Response(200, json=FUN_ROUTE))
    mock_couch(SEGMENT_ROWS)
    respx.post(f"{COUCH}/segments/_design/seek/_view/by_cell").mock(
        return_value=httpx.Response(404)  # view not built yet
    )
    resp = client.post("/api/route", json={"origin": ANN_ARBOR, "destination": DETROIT})
    assert resp.status_code == 200
    assert all(c["sought"] is None for c in resp.json()["candidates"])


def test_client_event_accepted_and_unknown_rejected():
    ok = client.post("/api/events", json={"type": "maps_opened", "fun_dial": 0.6})
    assert ok.status_code == 204
    bad = client.post("/api/events", json={"type": "totally_made_up"})
    assert bad.status_code == 422


@respx.mock
def test_couch_down_degrades_to_null_fun_index():
    respx.get(f"{GH}/route").mock(return_value=httpx.Response(200, json=FASTEST))
    respx.post(f"{GH}/route").mock(return_value=httpx.Response(200, json=FUN_ROUTE))
    respx.route(host="couch.test").mock(side_effect=httpx.ConnectError("couch down"))

    resp = client.post("/api/route", json={"origin": ANN_ARBOR, "destination": DETROIT})
    assert resp.status_code == 200
    assert all(c["fun_index"] is None for c in resp.json()["candidates"])


@respx.mock
def test_cache_hit_skips_graphhopper():
    gh_get = respx.get(f"{GH}/route").mock(return_value=httpx.Response(200, json=FASTEST))
    payload = {
        "candidates": [{
            "fun_dial": 0.0, "distance_m": 1.0, "time_s": 1.0, "dtime_s": 0.0,
            "fun_index": 0.5, "coordinates": [[-83.7, 42.2], [-83.6, 42.3]],
            "handoff": {
                "maps_url": "https://www.google.com/maps/dir/?api=1",
                "waypoints_used": 0, "worst_gap_excess_m": 0.0,
                "pinned": True, "verified": False,
            },
            "why": None,
            "sought": None,
        }]
    }
    mock_couch(cache_hit={"payload": payload, "expires": 9_999_999_999})

    resp = client.post("/api/route", json={"origin": ANN_ARBOR, "destination": DETROIT})
    assert resp.status_code == 200
    assert resp.json() == payload
    assert not gh_get.called


@respx.mock
def test_candidate_failure_still_ships_fastest():
    respx.get(f"{GH}/route").mock(return_value=httpx.Response(200, json=FASTEST))
    respx.post(f"{GH}/route").mock(side_effect=httpx.ConnectError("lm hiccup"))
    mock_couch(SEGMENT_ROWS)

    resp = client.post("/api/route", json={"origin": ANN_ARBOR, "destination": DETROIT})
    assert resp.status_code == 200
    cands = resp.json()["candidates"]
    assert len(cands) == 1
    assert cands[0]["fun_dial"] == 0.0


def test_rejects_out_of_range_coordinates():
    resp = client.post("/api/route", json={
        "origin": {"lat": 91.0, "lng": 0.0},
        "destination": DETROIT,
    })
    assert resp.status_code == 422


def test_rejects_excessive_distance():
    resp = client.post("/api/route", json={"origin": ANN_ARBOR, "destination": DENVER})
    assert resp.status_code == 422
    assert "maximum supported" in resp.json()["detail"]


@respx.mock
def test_graphhopper_down_returns_502():
    respx.get(f"{GH}/route").mock(side_effect=httpx.ConnectError("boom"))
    mock_couch()
    resp = client.post("/api/route", json={"origin": ANN_ARBOR, "destination": DETROIT})
    assert resp.status_code == 502


@respx.mock
def test_graphhopper_400_passes_message_through():
    respx.get(f"{GH}/route").mock(
        return_value=httpx.Response(400, json={"message": "Cannot find point 0"})
    )
    mock_couch()
    resp = client.post("/api/route", json={"origin": ANN_ARBOR, "destination": DETROIT})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Cannot find point 0"


def photon_payload():
    return {
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-85.6206, 44.7631]},
                "properties": {
                    "name": "Traverse City",
                    "state": "Michigan",
                    "country": "United States",
                    "osm_key": "place",
                    "osm_value": "city",
                },
            },
        ]
    }


@respx.mock
def test_geocode_ok():
    respx.get("https://photon.komoot.io/api").mock(
        return_value=httpx.Response(200, json=photon_payload())
    )
    resp = client.get("/api/geocode", params={"q": "traverse city"})
    assert resp.status_code == 200
    assert resp.json()["results"][0]["label"] == "Traverse City, Michigan"


def test_geocode_rejects_short_query():
    assert client.get("/api/geocode", params={"q": "a"}).status_code == 422


@respx.mock
def test_geocode_upstream_down_returns_502():
    respx.get("https://photon.komoot.io/api").mock(side_effect=httpx.ConnectError("boom"))
    assert client.get("/api/geocode", params={"q": "traverse city"}).status_code == 502


@respx.mock
def test_health_reports_graphhopper_state():
    respx.get(f"{GH}/health").mock(return_value=httpx.Response(200))
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "graphhopper": True}
