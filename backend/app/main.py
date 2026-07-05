from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .couch import CouchClient
from .events import LogEventEmitter
from .funindex import route_fun_index
from .geo import haversine_km
from .geocoder import GeocoderError, PhotonClient
from .graphhopper import GraphHopperClient, GraphHopperError
from .logging_setup import setup_logging
from .middleware import entitlement_middleware
from .schemas import GeocodeResponse, LatLng, RouteCandidate, RouteRequest, RouteResponse
from .scoring import custom_model_for, scoring

setup_logging(settings.log_level)

app = FastAPI(title="sassy-routes", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(entitlement_middleware)

gh = GraphHopperClient(settings.graphhopper_url, settings.graphhopper_timeout_s)
geocoder = PhotonClient(
    settings.geocoder_url,
    settings.geocoder_timeout_s,
    settings.geocode_bias_lat,
    settings.geocode_bias_lng,
)
couch = CouchClient(settings.couchdb_url, settings.couchdb_timeout_s)
events = LogEventEmitter()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "graphhopper": gh.health()}


@app.get("/api/geocode", response_model=GeocodeResponse)
def geocode(
    q: str = Query(min_length=2, max_length=200),
    limit: int = Query(5, ge=1, le=8),
) -> GeocodeResponse:
    try:
        results = geocoder.search(q, limit)
    except GeocoderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return GeocodeResponse(results=results)


@app.post("/api/route", response_model=RouteResponse)
def route(req: RouteRequest) -> RouteResponse:
    distance_km = haversine_km(
        req.origin.lat, req.origin.lng, req.destination.lat, req.destination.lng
    )
    if distance_km > settings.max_route_distance_km:
        raise HTTPException(
            status_code=422,
            detail=(
                f"origin and destination are {distance_km:.0f} km apart; "
                f"the maximum supported is {settings.max_route_distance_km:.0f} km"
            ),
        )

    cfg = scoring()
    key = _cache_key(req.origin, req.destination, cfg)
    cached = couch.cache_get(key)
    if cached is not None:
        _emit(req, cached["candidates"], cached=True)
        return RouteResponse(**cached)

    try:
        fastest = gh.fastest_route(req.origin, req.destination)
    except GraphHopperError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    rcfg = cfg["routing"]
    kept: list[dict] = [{"fun_dial": 0.0, **fastest}]
    for lam in rcfg["candidate_lambdas"]:
        try:
            cand = gh.custom_route(req.origin, req.destination, custom_model_for(lam, cfg))
        except GraphHopperError as exc:
            # partial degradation: fastest still ships even if a λ route fails
            events.emit("candidate_failed", {"fun_dial": lam, "detail": exc.detail})
            continue
        if cand["time_s"] > fastest["time_s"] * rcfg["max_time_multiplier"]:
            continue  # never a 3-hour detour for a 20-minute errand
        if _is_duplicate(cand, kept, rcfg["dedupe"]):
            continue
        kept.append({"fun_dial": lam, **cand})

    way_ids = sorted({w for c in kept for _, _, w in c["way_intervals"] if w is not None})
    segment_fun = couch.segment_fun(way_ids)
    default_fun = cfg["runtime"]["default_fun_index"]

    candidates = [
        RouteCandidate(
            fun_dial=c["fun_dial"],
            distance_m=c["distance_m"],
            time_s=c["time_s"],
            dtime_s=round(c["time_s"] - fastest["time_s"], 1),
            fun_index=route_fun_index(c["coordinates"], c["way_intervals"], segment_fun, default_fun),
            coordinates=c["coordinates"],
        )
        for c in kept
    ]
    resp = RouteResponse(candidates=candidates)

    couch.cache_put(key, resp.model_dump(), cfg["cache"]["route_ttl_seconds"])
    _emit(req, [c.model_dump(exclude={"coordinates"}) for c in candidates], cached=False)
    return resp


def _is_duplicate(cand: dict, kept: list[dict], tol: dict) -> bool:
    return any(
        abs(cand["time_s"] - k["time_s"]) < tol["time_s"]
        and abs(cand["distance_m"] - k["distance_m"]) < tol["distance_m"]
        for k in kept
    )


def _cache_key(origin: LatLng, destination: LatLng, cfg: dict) -> str:
    cell = cfg["cache"]["cell_size_deg"]
    q = lambda v: round(v / cell)  # noqa: E731
    return (
        f"v{cfg['version']}-{q(origin.lat)}_{q(origin.lng)}-"
        f"{q(destination.lat)}_{q(destination.lng)}"
    )


def _emit(req: RouteRequest, candidates: list[dict], cached: bool) -> None:
    events.emit("route_requested", {
        "origin": [req.origin.lat, req.origin.lng],
        "destination": [req.destination.lat, req.destination.lng],
        "cached": cached,
        "candidates": [
            {k: c.get(k) for k in ("fun_dial", "time_s", "dtime_s", "fun_index")}
            for c in candidates
        ],
    })
