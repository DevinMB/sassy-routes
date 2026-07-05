# sassy-routes

Self-hosted app that finds *fun* driving roads to a destination, lets you trade
fun against added time, and hands the chosen route to Google Maps so it just
works in Android Auto.

**Status: Phase 1** — the fun dial is live: each request returns the fastest
route plus fun-biased candidates (λ = 0.3/0.6/0.9) with a per-route **fun
index** (from our own segment scoring model) and the **time cost** vs. fastest.
Next up: the Google Maps handoff (Phase 2).

Note: "use my location" requires a secure context — it works on `localhost`
now and on the tunnel hostname once HTTPS is live, but not over plain
`http://<lan-ip>`.

## Stack

| Piece | Tech |
|---|---|
| Routing | [GraphHopper](https://www.graphhopper.com/) 9 (self-hosted), Michigan OSM extract |
| Backend | FastAPI + Pydantic v2 |
| Frontend | React + Vite + Leaflet |
| Storage | CouchDB (segment scores + route cache, from Phase 1) |
| Edge | Caddy (Cloudflare tunnel target in production) |

## Quickstart (homelab / anywhere with Docker)

```sh
make seed      # creates .env if missing, downloads the Michigan extract (~300 MB)
make up        # builds and starts everything
make pipeline  # scores all segments into CouchDB (~10-30 min, rerun after tuning scoring.yaml)
```

First start: GraphHopper imports the extract into a graph — including SRTM
elevation download and landmark prep (~10–20 min, watch `make logs`). Then open
**http://localhost:8080**, set origin and destination, and pick between the
fastest route and the fun candidates.

Useful:

```sh
make test         # backend tests (local python venv, no docker needed)
make clean-graph  # force graph reimport after refreshing the extract
make help         # everything else
```

Service layout: Caddy (`:8080`) fronts everything — `/api/*` → FastAPI,
everything else → the SPA. GraphHopper (`127.0.0.1:8989`) and CouchDB/Fauxton
(`127.0.0.1:5984/_utils`) are bound to localhost for debugging only.

## Exposing via Cloudflare tunnel

1. Cloudflare Zero Trust → Networks → Tunnels → create a tunnel.
2. Public hostname → service `http://caddy:80`.
3. Add `TUNNEL_TOKEN=...` to `.env`, uncomment the `cloudflared` service in
   `docker-compose.yml`, then `make up`.
4. Add `https://your-hostname` to `APEX_ALLOWED_ORIGINS` in `.env`.

Rate limiting rides on Cloudflare once the tunnel is live (stock Caddy has no
built-in rate limiter).

## Development

Backend (Python 3.12): `make test`, or for a live server:
`cd backend && uvicorn app.main:app --reload` (expects GraphHopper on
`localhost:8989`; override with `APEX_GRAPHHOPPER_URL`).

Frontend: `cd frontend && npm install && npm run dev` — Vite proxies `/api` to
`localhost:8000`. Tests: `npm test`.

Pipeline (scoring model, Python + numpy): `cd pipeline && uv venv && uv pip
install -r requirements.txt pytest && .venv/bin/python -m pytest`.

### How fun scoring works

- **Offline** (`make pipeline`): every car-routable OSM way gets a fun index
  ∈ [0,1] in CouchDB — curvature binned per 100 m (zeroed within 30 m of
  junctions/driveways: a curve at a blind driveway is a hazard, not fun),
  SRTM elevation relief, road-class preference, a hard unpaved gate (Miata
  rule), and safety gates that penalize dangerous geometry.
- **Online**: the backend asks GraphHopper for the fastest route (CH) plus one
  flexible route per fun-dial λ, using a per-request custom model that
  *penalizes* boring/conflict-prone roads (never rewards — keeps landmark
  search admissible and safety honest). Each candidate's fun index is the
  length-weighted average of its segments' scores, matched via `osm_way_id`
  path details. Candidates too close to the fastest are deduped; anything
  slower than `max_time_multiplier` × fastest is dropped.

All weights/thresholds live in [`scoring.yaml`](scoring.yaml) —
version-controlled, no magic numbers in code. After changing the
`gh_custom_model` section only, just restart the backend; after changing
pipeline weights, rerun `make pipeline`. Changing GraphHopper's
`graph.encoded_values` needs `make clean-graph && make up` (reimport).

## Roadmap

- [x] **Phase 0 — prove the pipe:** Compose stack, GraphHopper + Michigan, fastest A→B on a map
- [x] **Phase 1 — make it fun:** curvature/elevation precompute, fun index, fun dial, N candidates with Δtime
- [ ] **Phase 2 — the handoff:** waypoint compression + Google Maps deep link (the differentiator)
- [ ] **Phase 3 — pipeline hardening:** Kafka ingest + `apex.events` analytics stream
- [ ] **Phase 4 — monetize:** only on explicit go

## Data & licenses

- Road data © [OpenStreetMap](https://www.openstreetmap.org/copyright)
  contributors, [ODbL](https://opendatacommons.org/licenses/odbl/) — extracts
  via [Geofabrik](https://download.geofabrik.de/). Attribution is shown in the UI.
- Elevation: NASA SRTM (public domain) — Phase 1.
- Routing: [GraphHopper](https://github.com/graphhopper/graphhopper), Apache-2.0.

Drive responsibly. This app suggests enjoyable roads; it never encourages
speed. Obey posted limits and traffic laws.
