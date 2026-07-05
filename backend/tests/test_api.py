import json

import httpx
import respx
from fastapi.testclient import TestClient

from app.main import _cache_key, app
from app.schemas import LatLng

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

FASTEST = gh_path(10000, 600_000, COORDS_FAST, [[0, 2, 111]])
NEAR_DUPLICATE = gh_path(10050, 605_000, COORDS_FAST, [[0, 2, 111]])  # λ=0.3
FUN_ROUTE = gh_path(12000, 900_000, COORDS_FUN, [[0, 1, 222], [1, 2, 333]])  # λ=0.6
TOO_SLOW = gh_path(30000, 1_300_000, COORDS_FUN, [[0, 2, 222]])  # λ=0.9: > 2× fastest


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
