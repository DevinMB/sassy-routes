from typing import Literal

from pydantic import BaseModel, Field


class LatLng(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class RouteRequest(BaseModel):
    origin: LatLng
    destination: LatLng
    # Phase 1 adds the fun dial (lambda ∈ [0,1]) and returns N candidates.


class Handoff(BaseModel):
    # Google Maps deep link reproducing this route via ≤ max_waypoints pins.
    maps_url: str
    waypoints_used: int
    # Worst remaining per-gap excess (route path − chord) after compression —
    # the amount of detour Google could still shortcut between two waypoints.
    worst_gap_excess_m: float
    # False ⇒ the waypoint budget couldn't pin this route; UI warns and
    # offers GPX instead of a link Google would silently reroute.
    pinned: bool
    # True only when the optional Directions-API check confirmed the link.
    verified: bool = False


class ClientEvent(BaseModel):
    """Analytics events the frontend may emit (whitelist by design)."""

    type: Literal["maps_opened"]
    fun_dial: float | None = Field(default=None, ge=0, le=1)
    fun_index: float | None = Field(default=None, ge=0, le=1)
    dtime_s: float | None = None


class RouteWhy(BaseModel):
    """Why this route scored what it did — the five scoring.yaml criteria,
    length-weighted over the scored part of the route.

    curvature / elevation / road_class are contributions (higher = more fun).
    surface / safety are multiplicative gates (1.0 = no penalty applied).
    """

    curvature: float
    elevation: float
    road_class: float
    surface: float
    safety: float
    # Fraction of the route covered by scored segments (context for the above).
    scored_fraction: float


class SoughtRoad(BaseModel):
    """A standout road this candidate was deliberately routed through."""

    name: str | None
    fun_index: float
    length_m: float


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
    handoff: Handoff
    # Null when segment scores are unavailable (same condition as fun_index).
    why: RouteWhy | None = None
    # Set when this candidate was built by peak-seeking through a specific road.
    sought: SoughtRoad | None = None


class RouteResponse(BaseModel):
    # candidates[0] is always the fastest route (fun_dial 0).
    candidates: list[RouteCandidate]


class DriveRequest(BaseModel):
    origin: LatLng
    duration_min: float = Field(gt=0)


class DriveResponse(BaseModel):
    # A single randomized fun loop starting and ending at origin.
    distance_m: float
    time_s: float
    fun_index: float | None
    coordinates: list[tuple[float, float]]
    handoff: Handoff
    why: RouteWhy | None = None


class GeocodeResult(BaseModel):
    label: str
    lat: float
    lng: float
    type: str | None = None


class GeocodeResponse(BaseModel):
    results: list[GeocodeResult]
