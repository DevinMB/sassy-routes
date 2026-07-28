import math
import random

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .couch import CouchClient
from .deeplink import maps_deep_link
from .drive import loop_aim_points, nearest_tile, target_radius_km
from .events import LogEventEmitter
from .funindex import summarize_route
from .geo import haversine_km
from .geocoder import GeocoderError, PhotonClient
from .grid import aggregate, bbox_cells
from .graphhopper import GraphHopperClient, GraphHopperError
from .logging_setup import setup_logging
from .middleware import entitlement_middleware
from .schemas import (
    ClientEvent,
    DriveRequest,
    DriveResponse,
    GeocodeResponse,
    Handoff,
    LatLng,
    RouteCandidate,
    RouteRequest,
    RouteResponse,
    SoughtRoad,
)
from .scoring import custom_model_for, fingerprint, scoring
from .seek import corridor_cells, earned_detour_s, rank_targets
from .verify import HandoffVerifier
from .waypoints import compress, refine_on_road

# Bump whenever cached responses could change: schema edits AND behaviour
# changes in code. The fingerprint below covers scoring.yaml, so config is
# handled automatically — this constant is what covers *code*. Forgetting it
# serves stale routes that silently ignore the fix you just deployed.
CACHE_SCHEMA = "s6"

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
verifier = (
    HandoffVerifier(settings.google_api_key)
    if settings.handoff_verify and settings.google_api_key
    else None
)


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

    # Peak-seeking: a length-weighted average structurally ignores a brilliant
    # short road, so look for one near the corridor and route through it.
    seek_target = _seek_candidate(req, cfg, fastest, kept)
    if seek_target is not None:
        kept.append(seek_target)

    way_ids = sorted({w for c in kept for _, _, w in c["way_intervals"] if w is not None})
    segment_docs = couch.segment_docs(way_ids)
    default_fun = cfg["runtime"]["default_fun_index"]

    candidates = []
    for c in kept:
        fun_index, why = summarize_route(
            c["coordinates"], c["way_intervals"], segment_docs, default_fun
        )
        candidates.append(
            RouteCandidate(
                fun_dial=c["fun_dial"],
                distance_m=c["distance_m"],
                time_s=c["time_s"],
                dtime_s=round(c["time_s"] - fastest["time_s"], 1),
                fun_index=fun_index,
                coordinates=c["coordinates"],
                handoff=_handoff(c["coordinates"], c["way_intervals"], cfg, c["fun_dial"]),
                why=why,
                sought=c.get("sought"),
            )
        )
    resp = RouteResponse(candidates=candidates)

    couch.cache_put(key, resp.model_dump(), cfg["cache"]["route_ttl_seconds"])
    _emit(req, [c.model_dump(exclude={"coordinates"}) for c in candidates], cached=False)
    return resp


@app.post("/api/drive", response_model=DriveResponse)
def drive(req: DriveRequest) -> DriveResponse:
    """A randomized fun loop that starts and ends at origin, sized to fit
    duration_min. Aims at the same fun clusters the routing model scores."""
    cfg = scoring()
    dcfg = cfg["drive"]
    duration = max(dcfg["min_duration_min"], min(dcfg["max_duration_min"], req.duration_min))
    radius_km = target_radius_km(duration, dcfg)

    # fun clusters within reach (annulus bbox around origin), from the heat view
    reach = radius_km * (1 + dcfg["radius_jitter"]) + dcfg["snap_max_km"]
    cells = _bbox_cells_around(req.origin, reach, cfg["seek"]["cell_size_deg"])
    tiles = aggregate(couch.seek_rows(cells), cfg["seek"]["cell_size_deg"])
    if not tiles:
        raise HTTPException(422, "no good roads within range of that start point")

    model = custom_model_for(max(cfg["routing"]["candidate_lambdas"]), cfg)
    target_s = duration * 60.0
    rng = random.Random()  # fresh each call → a different loop every time
    best = None
    for _ in range(dcfg["max_attempts"]):
        aims = loop_aim_points(req.origin.lat, req.origin.lng, radius_km, dcfg, rng)
        vias = [nearest_tile(a[0], a[1], tiles, dcfg["snap_max_km"], rng) for a in aims]
        vias = [v for v in vias if v is not None]
        if not vias:
            continue
        points = (
            [[req.origin.lng, req.origin.lat]]
            + [[v["lng"], v["lat"]] for v in vias]
            + [[req.origin.lng, req.origin.lat]]
        )
        try:
            route = gh.route_points(points, model)
        except GraphHopperError:
            continue
        err = abs(route["time_s"] - target_s)
        if best is None or err < best[0]:
            best = (err, route)
        if err <= target_s * dcfg["time_tolerance"]:
            break

    if best is None:
        raise HTTPException(422, "couldn't build a loop from that start point")
    route = best[1]

    segment_docs = couch.segment_docs(
        sorted({w for _, _, w in route["way_intervals"] if w is not None})
    )
    fun_index, why = summarize_route(
        route["coordinates"], route["way_intervals"], segment_docs,
        cfg["runtime"]["default_fun_index"],
    )
    events.emit("drive_generated", {
        "duration_min": duration,
        "time_s": round(route["time_s"]),
        "fun_index": fun_index,
    })
    return DriveResponse(
        distance_m=route["distance_m"],
        time_s=route["time_s"],
        fun_index=fun_index,
        coordinates=route["coordinates"],
        handoff=_handoff(route["coordinates"], route["way_intervals"], cfg, fun_dial=1.0),
        why=why,
    )


@app.post("/api/events", status_code=204)
def client_event(ev: ClientEvent) -> Response:
    """Frontend analytics (e.g. "open in Maps" clicks) — the §6 metering seam."""
    events.emit(ev.type, ev.model_dump(exclude={"type"}))
    return Response(status_code=204)


def _bbox_cells_around(origin: LatLng, reach_km: float, cell_size_deg: float) -> list[list[int]]:
    """Grid cells within a square of half-width reach_km around origin."""
    lat_pad = reach_km / 110.574
    lng_pad = reach_km / max(111.320 * math.cos(math.radians(origin.lat)), 1e-6)
    return bbox_cells(
        origin.lat - lat_pad, origin.lng - lng_pad,
        origin.lat + lat_pad, origin.lng + lng_pad,
        cell_size_deg, max_cells=10_000,
    )


def _handoff(coordinates: list, way_intervals: list, cfg: dict, fun_dial: float) -> Handoff:
    hcfg = cfg["handoff"]
    if fun_dial == 0:
        # The fastest route needs no pinning: Google optimizes the same
        # objective (and adds live traffic). Origin → destination, no waypoints.
        return Handoff(
            maps_url=maps_deep_link(coordinates, []),
            waypoints_used=0,
            worst_gap_excess_m=0.0,
            pinned=True,
        )
    wp_idxs, gap_excess, pinned = compress(
        coordinates, hcfg["max_waypoints"], hcfg["max_gap_excess_m"]
    )
    # slide each waypoint onto a clean, junction-free stretch so Google's snap
    # doesn't produce loops or turnarounds (real failure seen on a drive)
    if wp_idxs:
        wp_idxs, gap_excess, pinned = refine_on_road(
            coordinates, way_intervals, wp_idxs,
            hcfg["max_gap_excess_m"], hcfg["waypoint_curve_penalty_m_per_deg"],
            hcfg["waypoint_junction_clearance_m"], hcfg["waypoint_center_window_frac"],
        )
    verified = False
    if verifier is not None:
        wp_idxs, verified = verifier.verify(
            coordinates,
            wp_idxs,
            hcfg["max_waypoints"],
            hcfg["verify_max_deviation_m"],
            hcfg["verify_max_attempts"],
        )
    return Handoff(
        maps_url=maps_deep_link(coordinates, wp_idxs),
        waypoints_used=len(wp_idxs),
        worst_gap_excess_m=gap_excess,
        pinned=pinned,
        verified=verified,
    )


def _seek_candidate(
    req: RouteRequest, cfg: dict, fastest: dict, kept: list[dict]
) -> dict | None:
    """Route through the best standout road near the corridor, if one fits.

    Best-effort: any failure (no view, no target, over budget) simply means no
    seek candidate — the normal candidates are unaffected.
    """
    scfg = cfg["seek"]
    cells = corridor_cells(
        req.origin, req.destination, scfg["cell_size_deg"], scfg["corridor_buffer_km"]
    )
    targets = rank_targets(couch.seek_rows(cells), req.origin, req.destination, scfg)
    if not targets:
        return None

    ceiling_s = fastest["time_s"] * scfg["max_time_multiplier"]
    # strongest dial available — if we're detouring on purpose, commit to it
    model = custom_model_for(max(cfg["routing"]["candidate_lambdas"]), cfg)

    # Charge the road only for the detour IT causes. The seek route uses the
    # strongest fun model, which already wanders well off the fastest line, so
    # measuring against `fastest` billed every road for the dial's cost too
    # (measured: 23 min "detour" for a road 0.9 km off the corridor, of which
    # 21.4 min was the fun route's own wandering).
    baseline_s = max((k["time_s"] for k in kept if k["fun_dial"] > 0), default=fastest["time_s"])

    # Route through every shortlisted target and keep the best, rather than
    # taking the first that merely fits: the cheapest-to-reach road is often
    # not the one worth going for, and vice versa.
    best: dict | None = None
    for target in targets:
        via = LatLng(lat=target["lat"], lng=target["lng"])
        try:
            route = gh.custom_route(req.origin, req.destination, model, via=via)
        except GraphHopperError as exc:
            events.emit("seek_failed", {"detail": exc.detail, "road": target["name"]})
            continue
        extra_s = route["time_s"] - baseline_s
        if route["time_s"] > ceiling_s or extra_s > earned_detour_s(target, scfg):
            events.emit("seek_rejected", {
                "road": target["name"],
                "extra_s": round(extra_s),
                "earned_s": round(earned_detour_s(target, scfg)),
            })
            continue
        if _is_duplicate(route, kept, cfg["routing"]["dedupe"]):
            continue  # already covered — try the next-best road, don't give up
        if best is None or target["value"] > best["target"]["value"]:
            best = {"route": route, "target": target}

    if best is None:
        return None
    target = best["target"]
    return {
        "fun_dial": 1.0,
        **best["route"],
        "sought": SoughtRoad(
            name=target["name"],
            fun_index=target["fun_index"],
            length_m=target["length_m"],
        ),
    }


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
        f"{CACHE_SCHEMA}-{fingerprint()}-{q(origin.lat)}_{q(origin.lng)}-"
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
