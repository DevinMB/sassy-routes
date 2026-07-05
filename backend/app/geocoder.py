import httpx


class GeocoderError(Exception):
    """Geocoding failed; carries the HTTP status the API should return."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class PhotonClient:
    """Thin client for a Photon geocoder (photon.komoot.io or self-hosted)."""

    def __init__(self, base_url: str, timeout_s: float, bias_lat: float, bias_lng: float):
        self._bias = {"lat": bias_lat, "lon": bias_lng}
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout_s,
            headers={"User-Agent": "sassy-routes/0.1 (self-hosted homelab app)"},
        )

    def search(self, query: str, limit: int) -> list[dict]:
        params = {"q": query, "limit": limit, "lang": "en", **self._bias}
        try:
            resp = self._client.get("/api", params=params)
        except httpx.TimeoutException:
            raise GeocoderError(504, "geocoder timed out")
        except httpx.HTTPError:
            raise GeocoderError(502, "geocoder is unreachable")
        if resp.status_code != 200:
            raise GeocoderError(502, "geocoder returned an error")

        results = []
        for feature in resp.json().get("features", []):
            try:
                lng, lat = feature["geometry"]["coordinates"][:2]
            except (KeyError, ValueError, TypeError):
                continue
            props = feature.get("properties", {})
            results.append({
                "label": _label(props),
                "lat": lat,
                "lng": lng,
                "type": props.get("osm_value"),
            })
        return results


def _label(props: dict) -> str:
    street = props.get("street")
    if street and props.get("housenumber"):
        street = f"{props['housenumber']} {street}"
    primary = props.get("name") or street or "unnamed"
    parts = [primary, props.get("city") or props.get("county"), props.get("state")]
    seen: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return ", ".join(seen)
