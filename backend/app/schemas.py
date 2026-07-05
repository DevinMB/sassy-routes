from pydantic import BaseModel, Field


class LatLng(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class RouteRequest(BaseModel):
    origin: LatLng
    destination: LatLng
    # Phase 1 adds the fun dial (lambda ∈ [0,1]) and returns N candidates.


class RouteCandidate(BaseModel):
    # Fun dial λ ∈ [0,1] this candidate was routed with (0 = fastest).
    fun_dial: float
    distance_m: float
    time_s: float
    # Time cost vs. the fastest route ("+18 min" in the UI).
    dtime_s: float
    # Length-weighted fun index from CouchDB segment scores; null when
    # segment data is unavailable (routing still works — graceful degradation).
    fun_index: float | None
    # GeoJSON order: [lng, lat] pairs.
    coordinates: list[tuple[float, float]]


class RouteResponse(BaseModel):
    # candidates[0] is always the fastest route (fun_dial 0).
    candidates: list[RouteCandidate]


class GeocodeResult(BaseModel):
    label: str
    lat: float
    lng: float
    type: str | None = None


class GeocodeResponse(BaseModel):
    results: list[GeocodeResult]
