#!/usr/bin/env bash
# Seed script: fetch the Michigan OSM extract so `docker compose up` can build
# the GraphHopper graph unattended. Idempotent and resumable; verifies the
# Geofabrik MD5 before accepting the file.
set -euo pipefail
cd "$(dirname "$0")/.."

EXTRACT_URL="${EXTRACT_URL:-https://download.geofabrik.de/north-america/us/michigan-latest.osm.pbf}"
PBF="data/osm/$(basename "$EXTRACT_URL")"

# pre-create as the invoking user so containers (root or uid-1000) can write
mkdir -p data/osm data/graph-cache data/couchdb data/srtm data/elevation

if [ -f "$PBF" ]; then
    echo "extract already present: $PBF (delete it and re-run to refresh)"
    exit 0
fi

echo "downloading $EXTRACT_URL ..."
curl -fL --retry 3 --retry-delay 5 -C - -o "$PBF.part" "$EXTRACT_URL"

echo "verifying checksum ..."
expected=$(curl -fsL "$EXTRACT_URL.md5" | awk '{print $1}')
actual=$(md5sum "$PBF.part" | awk '{print $1}')
if [ "$expected" != "$actual" ]; then
    echo "MD5 mismatch (expected $expected, got $actual) — leaving $PBF.part for resume" >&2
    exit 1
fi

mv "$PBF.part" "$PBF"
echo "done: $PBF"
echo "next: 'make up' — first graphhopper start imports the graph (~5-15 min)"
