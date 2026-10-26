# sassy-routes

Self-hosted app that finds *fun* driving roads to a destination, lets you trade
fun against added time, and hands the chosen route to Google Maps so it just
works in Android Auto.

**Status: Phase 2** — the full loop works: pick a fun level, get candidates
with fun index + time cost, and **open the chosen route in Google Maps** (works
in Android Auto). Waypoint compression pins Google to our route with ≤ 9
waypoints; when a route is too twisty to pin, the UI says so and offers a GPX
instead of a silently-broken link.

Note: "use my location" requires a secure context — it works on `localhost`
and on the HTTPS tunnel hostname, but not over plain `http://<lan-ip>`.

## Production (since 2026-10-26)

Production runs from **DevinMB/homelab-stacks** (`sites/home/sassy-routes`), deployed by `stack-sync` on the sassy-routes VM:

- **Ship:** merge to `main`. CI builds and tests the images (`sassy-routes-backend`, `-frontend`, `-edge`, `-pipeline`), and production picks the new build up within about 10 minutes. `scoring.yaml` is baked into the backend image, so a scoring change ships the same way.
- **Beta (`/beta`):** push to the `beta` branch; CI builds `sassy-routes-frontend-beta` and `/beta` serves it. **Promote:** open a PR from `beta` into `main`.
- **Data jobs stay on the VM:** `make pipeline`, `make import-graph` and `make retune` run from the working copy as before (data lives in `/srv/stacks/sassy-routes/data`; `./data` points there). GraphHopper reads its config from this working copy, because a config change always needs a graph rebuild: pull `main` here first.
- `make up`, `tunnel`, `beta`, `promote` and `down` refuse on the production VM; they are for local development.

## Stack

| Piece | Tech |
|---|---|
| Routing | [GraphHopper](https://www.graphhopper.com/) 9 (self-hosted), Michigan OSM extract |
| Backend | FastAPI + Pydantic v2 |
| Frontend | React + Vite + Leaflet |
| Storage | CouchDB (segment scores + route cache, from Phase 1) |
| Edge | nginx (Cloudflare tunnel target in production) |

## Quickstart (homelab / anywhere with Docker)

```sh
make seed          # creates .env if missing, downloads the Michigan extract (~300 MB)
make up            # builds and starts everything
make pipeline      # scores all segments into CouchDB + fun CSV (~5-10 min)
make import-graph  # bakes fun scores into the routing graph (~10 min, site stays up)
```

First start: GraphHopper imports the extract into a graph — including SRTM
elevation download and landmark prep (~10–20 min, watch `make logs`). Then open
**http://localhost:8080**, set origin and destination, and pick between the
fastest route and the fun candidates.

Useful:

```sh
make test          # backend tests (local python venv, no docker needed)
make beta          # rebuild the staging UI at /beta (production untouched)
make promote       # ship what's on /beta to production
make reload-proxy  # apply infra/edge/nginx.conf edits (rebuilds the edge image)
make clean-graph   # force graph reimport after refreshing the extract
make help          # everything else
```

### Retuning without downtime

`make import-graph` builds into `data/graph-staging` while the live graph keeps
serving, then stops GraphHopper only for the directory swap — about a minute of
reload instead of the ~10 minutes the import takes. A failed import never
touches the running graph, since the swap only happens on success.

Note: `scoring()` is cached per process, so **restart the backend after editing
`scoring.yaml`**. Cached route responses are keyed by a hash of that file, so a
config change invalidates them automatically.

### Trying UI changes on /beta

The staging UI lives at `/beta` on the same host, sharing the same API and
backend. It's built from the same source tree with `VITE_BASE=/beta/`, so
`make beta` rebuilds only that container — production keeps serving the last
image `make up`/`make promote` built. Iterate on `/beta`, then `make promote`.

Service layout: the nginx edge (`:8080`) fronts everything — `/api/*` → FastAPI,
everything else → the SPA. GraphHopper (`127.0.0.1:8989`) and CouchDB/Fauxton
(`127.0.0.1:5984/_utils`) are bound to localhost for debugging only.

## Exposing via Cloudflare tunnel

Public URL: **https://sassyroutes.devinbutts.net** (already in
`APEX_ALLOWED_ORIGINS`).

1. Cloudflare Zero Trust → Networks → Tunnels → create a tunnel; copy its token.
2. Add a **Public Hostname**: `sassyroutes.devinbutts.net` → type **HTTP**,
   URL **`edge:80`**. (HTTP, not HTTPS: Cloudflare terminates TLS and
   reaches the edge over the internal docker network.)
3. Paste the token into `TUNNEL_TOKEN=` in `.env`, then `make tunnel`.

`make tunnel` starts the whole stack including the `cloudflared` service (it
lives behind the `tunnel` compose profile, so a plain `make up` never touches
it). To fold the tunnel into `make up` on the prod box, set
`COMPOSE_PROFILES=tunnel` in `.env`. Once it's live, "use my location" works
(HTTPS is a secure context) and rate limiting can ride on Cloudflare (the
edge does no rate limiting itself).

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
  rule), and safety gates that penalize dangerous geometry. Residential
  streets are penalized by default (subdivision mazes), but a *slow,
  low-junction-density* residential way is promoted to near-tertiary — that's
  how genuinely curvy neighborhood roads (e.g. East Grand Rapids' Portman/
  Maplevalley/Oran) become eligible; the tight-curve-at-low-limit safety gate
  can still veto goat paths.
- **Injection** (`make import-graph`): the pipeline's scores are baked into
  the routing graph as a custom `apex_fun` encoded value by a small Java
  sidecar ([infra/gh-import](infra/gh-import)) — import-time only; serving
  stays on the stock GraphHopper image, which happily loads the finished
  graph. (GraphHopper's built-in `curvature` EV proved useless for sweeper
  roads: it quantizes to 0.05 and reads Patterson Lake Rd as 82% straight.)
- **Online**: the backend asks GraphHopper for the fastest route (CH) plus one
  flexible route per fun-dial λ, using a per-request custom model that
  *penalizes* low-`apex_fun` edges (never rewards — keeps landmark search
  admissible and safety honest). **The dial routes on the exact score the UI
  displays.** Each candidate's fun index is the length-weighted average of its
  segments' scores, matched via `osm_way_id` path details. Candidates too
  close to an already-kept route are deduped (in fun-road country the fastest
  route often *is* the funnest — you'll see a single card); anything slower
  than `max_time_multiplier` × fastest is dropped.

### The Google Maps handoff

Google re-routes between the waypoints you hand it, so each candidate ships
with a deep link built by **waypoint compression**: gaps whose route path
exceeds their straight chord by more than `handoff.max_gap_excess_m` get a
waypoint at the detour apex (excess length is what Google's fastest-preference
would shortcut; smooth curve sag is deliberately not counted). The fastest
candidate hands off waypoint-free — Google optimizes the same objective and
adds live traffic. If ≤ 9 waypoints can't pin a route, `pinned: false` comes
back and the UI warns + offers GPX export.

**Verified mode (optional, off by default, costs money):** set
`APEX_HANDOFF_VERIFY=true` and `APEX_GOOGLE_API_KEY=...` to have the backend
check each link against the Google Directions API (`via:` waypoints) and
insert extra waypoints where Google's interpretation diverges.

All weights/thresholds live in [`scoring.yaml`](scoring.yaml) —
version-controlled, no magic numbers in code.

### After editing scoring.yaml

```sh
make retune
```

That's the whole answer. Some sections (`curvature`, `elevation`,
`road_class`, `surface`, `safety`, `blend`, `conflict_points`) change every
road's stored score, so they need a rescore and a graph rebuild — about 15
minutes, with the site up throughout. The rest are read live and only need a
backend restart, which takes a second. `make retune` hashes the
score-affecting sections, compares against the last rescore, and does only
what's actually required; `FORCE=1 make retune` does everything regardless.

The backend restart is not optional even for a config-only edit: `scoring()`
is cached for the process lifetime, so an edit without a restart changes
nothing. Cached *routes* invalidate themselves — their key hashes the file.

## Roadmap

- [x] **Phase 0 — prove the pipe:** Compose stack, GraphHopper + Michigan, fastest A→B on a map
- [x] **Phase 1 — make it fun:** curvature/elevation precompute, fun index, fun dial, N candidates with Δtime
- [x] **Phase 2 — the handoff:** waypoint compression + Google Maps deep link (the differentiator)
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
