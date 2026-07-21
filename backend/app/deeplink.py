"""Google Maps deep-link construction.

Uses the documented Maps URLs form (api=1) — an intended use per Google's
Maps URLs docs (guardrail 7). The undocumented /maps/dir/.../data=!4m…
path form can express true via-points but is fragile; revisit after testing
the api=1 form on a real head unit.
"""
from urllib.parse import urlencode

BASE = "https://www.google.com/maps/dir/?"


def _fmt(coord: list) -> str:
    # GeoJSON [lng, lat] → "lat,lng", 6 decimals (~0.1 m)
    return f"{coord[1]:.6f},{coord[0]:.6f}"


def maps_deep_link(coordinates: list, waypoint_indices: list[int]) -> str:
    params = {
        "api": 1,
        "origin": _fmt(coordinates[0]),
        "destination": _fmt(coordinates[-1]),
        "travelmode": "driving",
    }
    if waypoint_indices:
        params["waypoints"] = "|".join(_fmt(coordinates[i]) for i in waypoint_indices)
    return BASE + urlencode(params, safe=",|")
