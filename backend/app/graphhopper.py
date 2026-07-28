import httpx

from .schemas import LatLng


class GraphHopperError(Exception):
    """Routing failed; carries the HTTP status the API should return."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class GraphHopperClient:
    def __init__(self, base_url: str, timeout_s: float):
        self._client = httpx.Client(base_url=base_url, timeout=timeout_s)

    def health(self) -> bool:
        try:
            return self._client.get("/health").status_code == 200
        except httpx.HTTPError:
            return False

    def fastest_route(self, origin: LatLng, destination: LatLng) -> dict:
        """Fastest car route via CH — the Δtime baseline."""
        params = [
            ("point", f"{origin.lat},{origin.lng}"),
            ("point", f"{destination.lat},{destination.lng}"),
            ("profile", "car"),
            ("points_encoded", "false"),
            ("instructions", "false"),
            ("calc_points", "true"),
            ("details", "osm_way_id"),
            ("locale", "en"),
        ]
        try:
            resp = self._client.get("/route", params=params)
        except httpx.TimeoutException:
            raise GraphHopperError(504, "routing engine timed out")
        except httpx.HTTPError:
            raise GraphHopperError(502, "routing engine is unreachable")
        return self._parse(resp)

    def custom_route(
        self,
        origin: LatLng,
        destination: LatLng,
        custom_model: dict,
        via: LatLng | None = None,
    ) -> dict:
        """Flexible (LM) route with a per-request custom model — the fun dial.

        `via` forces the route through a point (peak-seeking): GraphHopper
        treats intermediate points as hard constraints.
        """
        points = [[origin.lng, origin.lat]]
        if via is not None:
            points.append([via.lng, via.lat])
        points.append([destination.lng, destination.lat])
        return self.route_points(points, custom_model)

    def route_points(self, points: list[list[float]], custom_model: dict) -> dict:
        """Flexible (LM) route through an explicit [lng,lat] point list — used
        for multi-waypoint loops (take-me-for-a-drive) as well as single vias."""
        body = {
            "points": points,
            "profile": "car",
            "ch.disable": True,
            # a via-point shouldn't force a U-turn if the road runs the other way
            "pass_through": True,
            "points_encoded": False,
            "instructions": False,
            "details": ["osm_way_id"],
            "locale": "en",
            "custom_model": custom_model,
        }
        try:
            resp = self._client.post("/route", json=body)
        except httpx.TimeoutException:
            raise GraphHopperError(504, "routing engine timed out")
        except httpx.HTTPError:
            raise GraphHopperError(502, "routing engine is unreachable")
        return self._parse(resp)

    @staticmethod
    def _parse(resp: httpx.Response) -> dict:
        if resp.status_code != 200:
            # GH 400s carry useful, safe messages ("Cannot find point 0: ...")
            try:
                message = resp.json().get("message", "routing failed")
            except ValueError:
                message = "routing failed"
            status = 400 if resp.status_code == 400 else 502
            raise GraphHopperError(status, message)

        paths = resp.json().get("paths") or []
        if not paths:
            raise GraphHopperError(502, "routing engine returned no route")
        path = paths[0]
        return {
            "distance_m": path["distance"],
            "time_s": path["time"] / 1000.0,  # GH reports milliseconds
            "coordinates": path["points"]["coordinates"],
            # [[from_idx, to_idx, way_id], ...] over the coordinate array
            "way_intervals": path.get("details", {}).get("osm_way_id", []),
        }
