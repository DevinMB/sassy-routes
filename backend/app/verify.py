"""Optional verified handoff (CLAUDE-ref §5) — OFF by default.

When APEX_HANDOFF_VERIFY=true and a Google API key is set, we ask the
Directions API how Google interprets our waypoint chain (via: waypoints — no
stopover legs, mirrors deep-link dragging behavior), measure how far its route
strays from ours, and insert extra waypoints at the worst divergence. Costs
money per request; keep it opt-in (guardrail 7: proper key, proper terms).
"""
import logging

import httpx

from .waypoints import _point_segment_m, project

logger = logging.getLogger("apex.verify")


def decode_polyline(encoded: str) -> list[list[float]]:
    """Google encoded polyline → [[lng, lat], ...]."""
    coords, index, lat, lng = [], 0, 0, 0
    while index < len(encoded):
        for target in ("lat", "lng"):
            shift, result = 0, 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if target == "lat":
                lat += delta
            else:
                lng += delta
        coords.append([lng / 1e5, lat / 1e5])
    return coords


class HandoffVerifier:
    def __init__(self, api_key: str, timeout_s: float = 10.0):
        self._key = api_key
        self._client = httpx.Client(
            base_url="https://maps.googleapis.com", timeout=timeout_s
        )

    def verify(
        self,
        coordinates: list,
        waypoint_indices: list[int],
        max_waypoints: int,
        max_deviation_m: float,
        max_attempts: int,
    ) -> tuple[list[int], bool]:
        """Returns (possibly extended waypoint indices, verified)."""
        idxs = list(waypoint_indices)
        for _ in range(max_attempts):
            google_coords = self._google_route(coordinates, idxs)
            if google_coords is None:
                return idxs, False
            dev, worst = _route_deviation(coordinates, google_coords)
            if dev <= max_deviation_m:
                return idxs, True
            if len(idxs) >= max_waypoints or worst < 0:
                logger.info("verify: cannot pin further (dev %.0f m)", dev)
                return idxs, False
            idxs = sorted({*idxs, worst})
        return idxs, False

    def _google_route(self, coordinates: list, idxs: list[int]) -> list | None:
        params = {
            "origin": f"{coordinates[0][1]:.6f},{coordinates[0][0]:.6f}",
            "destination": f"{coordinates[-1][1]:.6f},{coordinates[-1][0]:.6f}",
            "mode": "driving",
            "key": self._key,
        }
        if idxs:
            params["waypoints"] = "|".join(
                f"via:{coordinates[i][1]:.6f},{coordinates[i][0]:.6f}" for i in idxs
            )
        try:
            resp = self._client.get("/maps/api/directions/json", params=params)
            body = resp.json()
            if body.get("status") != "OK" or not body.get("routes"):
                logger.warning("directions api status: %s", body.get("status"))
                return None
            return decode_polyline(body["routes"][0]["overview_polyline"]["points"])
        except Exception as exc:  # noqa: BLE001 — verification is best-effort
            logger.warning("directions api failed: %s", exc)
            return None


def _route_deviation(ours: list, theirs: list) -> tuple[float, int]:
    """Asymmetric max deviation: our vertices vs their polyline.

    Catches Google skipping our detours (our apex vertices end up far from its
    path). Returns (deviation_m, index of our worst vertex)."""
    if len(theirs) < 2:
        return float("inf"), -1
    combined = ours + theirs
    xs, ys = project(combined)
    n = len(ours)
    gx, gy = xs[n:], ys[n:]
    step = max(1, n // 250)  # sampling keeps this O(250 × |theirs|)
    worst, worst_idx = 0.0, -1
    for i in range(1, n - 1, step):
        d = min(
            _point_segment_m(xs[i], ys[i], gx[j], gy[j], gx[j + 1], gy[j + 1])
            for j in range(len(gx) - 1)
        )
        if d > worst:
            worst, worst_idx = d, i
    return worst, worst_idx
