#!/usr/bin/env bash
# Apply scoring.yaml changes, doing only the work they actually require.
#
# Some sections change every road's stored score (so CouchDB must be rescored
# and the routing graph rebuilt); the rest are read live by the backend and
# only need a restart. Getting that wrong is quiet rather than loud — you look
# at results that silently ignore your edit — so this decides for you by
# hashing the score-affecting sections and comparing with the last rescore.
#
#   make retune          do what's needed
#   FORCE=1 make retune  rescore and rebuild regardless
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE="${COMPOSE:-docker compose}"
HASH_FILE="data/.score-hash"
IMAGE="sassy-routes-pipeline"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "building the pipeline image first..."
    $COMPOSE build pipeline
fi

# Sections that determine each segment's fun_index, plus the two seek settings
# baked into CouchDB documents and the seek view by the pipeline.
current=$(docker run --rm -v "$PWD/scoring.yaml:/s.yaml:ro" "$IMAGE" python -c "
import hashlib, json, yaml
cfg = yaml.safe_load(open('/s.yaml'))
seek = cfg.get('seek') or {}
scored = {k: cfg.get(k) for k in
          ('curvature', 'conflict_points', 'elevation', 'road_class',
           'surface', 'safety', 'blend')}
scored['seek_index'] = {k: seek.get(k) for k in ('min_fun_index', 'cell_size_deg')}
print(hashlib.sha256(json.dumps(scored, sort_keys=True, default=str).encode()).hexdigest()[:16])
")

previous=$(cat "$HASH_FILE" 2>/dev/null || echo "")

if [ "${FORCE:-}" = "1" ] || [ "$current" != "$previous" ]; then
    if [ -z "$previous" ]; then
        echo "no record of the last rescore — doing a full retune to be safe"
    else
        echo "segment scoring changed — rescoring and rebuilding the graph"
    fi
    echo "(~15 min; the site keeps serving until a brief swap at the end)"
    make pipeline
    make import-graph
    mkdir -p data
    echo "$current" > "$HASH_FILE"
else
    echo "segment scores unchanged — skipping the rescore and graph rebuild"
fi

# Always: scoring.yaml is cached for the backend process's lifetime, so
# without this a config-only edit does nothing at all.
$COMPOSE restart backend
echo
echo "retune complete — new config is live"
