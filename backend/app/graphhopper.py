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
        self, origin: LatLng, destination: LatLng, custom_model: dict
    ) -> dict:
        """Flexible (LM) route with a per-request custom model — the fun dial.

        Straight origin→destination. Anything that needs intermediate points
        (peak-seeking, drive loops) builds its own list and calls
        `route_points` — pinning a road takes both of its ends, which this
        signature can't express.
        """
        points = [[origin.lng, origin.lat], [destination.lng, destination.lat]]
        return self.route_points(points, custom_model)

    def route_points(self, points: list[list[float]], custom_model: dict) -> dict:
        """Flexible (LM) route through an explicit [lng,lat] point list — used
        for multi-waypoint loops (take-me-for-a-drive) as well as single vias."""
        # NOTE: no `pass_through` here. It reads like the fix for "a via point
        # shouldn't force a U-turn if the road runs the other way", and it was
        # in this body for exactly that reason, but GraphHopper ignores it —
        # measured on 9.0, and measured again on 11.0 after that major bump:
        # the server accepts `"pass_through": "NOT_A_BOOL"` without complaint,
        # exactly as it accepts an invented field name, and routes identically
        # (distance, time and geometry alike) with it true, false and absent.
        # The 11.0 check deliberately used two-way rural roads, where a U-turn
        # is physically possible and the router demonstrably takes one (227 m
        # out, 65 m back, a 358 m route); the flag does not stop it there
        # either. A first attempt on freeway geometry proved nothing, since a
        # divided highway forbids the U-turn anyway. Sending it bought nothing
        # except the false impression that via U-turns were handled. They are
        # not — the caller has to price the shape it got back (see overlap.py).
        body = {
            "points": points,
            "profile": "car",
            "ch.disable": True,
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
