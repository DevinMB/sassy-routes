"""Offline segment scorer: OSM extract → fun_index per way → CouchDB.

Run via: docker compose run --rm pipeline   (or `make pipeline`)

Pass 1 finds junction nodes (nodes shared by ≥2 car-routable ways — includes
driveway/side-road connections, the conflict points). Pass 2 scores every
car-routable way and bulk-writes docs to the `segments` db.

Phase 3 moves this onto Kafka; it must stay fully independent of the online
routing path (guardrail 3).
"""
import logging
import math as mth
import time
from array import array

import numpy as np
import osmium

from .config import CAR_HIGHWAYS, env, load_scoring
from .couch import CouchWriter
from .score import score_way
from .srtm import SrtmSampler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
# httpx INFO logs full request URLs — which include CouchDB credentials.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("scorer")

BATCH = 2000
LOG_EVERY = 200_000


class JunctionPass(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.refs = array("q")

    def way(self, w):
        if w.tags.get("highway") in CAR_HIGHWAYS:
            self.refs.extend(n.ref for n in w.nodes)


class ScorePass(osmium.SimpleHandler):
    def __init__(self, junctions: np.ndarray, srtm: SrtmSampler, couch: CouchWriter, cfg: dict):
        super().__init__()
        self.junctions = junctions  # sorted node ids
        self.srtm = srtm
        self.couch = couch
        self.cfg = cfg
        self.buffer: list[dict] = []
        self.scored = 0
        self.skipped = 0
        self.no_elevation = 0
        # (way_id, fun×100) pairs for the GraphHopper apex_fun encoded value
        self.fun_rows: list[tuple[int, int]] = []

    def way(self, w):
        if w.tags.get("highway") not in CAR_HIGHWAYS:
            return
        refs, lats, lngs = array("q"), array("d"), array("d")
        for n in w.nodes:
            if n.location.valid():
                refs.append(n.ref)
                lats.append(n.location.lat)
                lngs.append(n.location.lon)
        if len(lats) < 2:
            self.skipped += 1
            return

        lats_np = np.frombuffer(lats, dtype=np.float64)
        lngs_np = np.frombuffer(lngs, dtype=np.float64)
        refs_np = np.frombuffer(refs, dtype=np.int64)

        idx = np.searchsorted(self.junctions, refs_np)
        idx = np.minimum(idx, len(self.junctions) - 1)
        junction_mask = self.junctions[idx] == refs_np if len(self.junctions) else np.zeros(len(refs_np), bool)

        elevs = self.srtm.elevations(lats_np, lngs_np)
        if elevs is None:
            self.no_elevation += 1

        doc = score_way(dict(w.tags), lats_np, lngs_np, junction_mask, elevs, self.cfg)
        if doc is None:
            self.skipped += 1
            return
        doc["_id"] = f"way:{w.id}"
        doc["scoring_version"] = self.cfg["version"]
        # Midpoint + grid cell make the segment findable by area, which is what
        # peak-seeking needs (route deliberately through a great short road).
        # Without these the docs carry no geometry at all.
        mid = len(lats_np) // 2
        cell = self.cfg["seek"]["cell_size_deg"]
        doc["mid"] = [round(float(lats_np[mid]), 6), round(float(lngs_np[mid]), 6)]
        doc["cell"] = [int(mth.floor(doc["mid"][0] / cell)), int(mth.floor(doc["mid"][1] / cell))]
        self.buffer.append(doc)
        self.fun_rows.append((w.id, round(doc["fun_index"] * 100)))
        self.scored += 1
        if len(self.buffer) >= BATCH:
            self.couch.bulk(self.buffer)
            self.buffer = []
        if self.scored % LOG_EVERY == 0:
            logger.info("scored %d ways so far", self.scored)


def main() -> None:
    cfg = load_scoring()
    pbf = env("APEX_OSM_PBF", "/data/osm/michigan-latest.osm.pbf")
    couch = CouchWriter(env("APEX_COUCHDB_URL", "http://couchdb:5984"), "segments")
    srtm = SrtmSampler(env("APEX_SRTM_CACHE", "/data/srtm"))

    t0 = time.time()
    logger.info("pass 1: junction detection over %s", pbf)
    p1 = JunctionPass()
    p1.apply_file(pbf)
    refs = np.frombuffer(p1.refs, dtype=np.int64)
    ids, counts = np.unique(refs, return_counts=True)
    junctions = ids[counts >= 2]
    logger.info(
        "pass 1 done in %.0fs: %d way-nodes, %d junction nodes",
        time.time() - t0, len(refs), len(junctions),
    )
    del p1, refs, ids, counts

    couch.recreate_db()
    t1 = time.time()
    logger.info("pass 2: scoring ways")
    p2 = ScorePass(junctions, srtm, couch, cfg)
    p2.apply_file(pbf, locations=True, idx="flex_mem")
    couch.bulk(p2.buffer)
    logger.info(
        "pass 2 done in %.0fs: scored=%d skipped=%d no_elevation=%d",
        time.time() - t1, p2.scored, p2.skipped, p2.no_elevation,
    )

    couch.put_seek_view(cfg["seek"]["min_fun_index"])

    # scores for GraphHopper's apex_fun encoded value (read by gh-import;
    # run `make import-graph` after this to bake them into the routing graph)
    csv_path = env("APEX_FUN_CSV", "/data/scores/apex-fun.csv")
    with open(csv_path, "w") as fh:
        fh.write("way_id,fun\n")
        for way_id, fun in p2.fun_rows:
            fh.write(f"{way_id},{fun}\n")
    logger.info("wrote %d fun scores to %s", len(p2.fun_rows), csv_path)

    # cached route responses embed fun indexes — stale after a rescore
    CouchWriter(env("APEX_COUCHDB_URL", "http://couchdb:5984"), "route_cache").recreate_db()
    logger.info("flushed route cache")
    logger.info("total %.0fs", time.time() - t0)


if __name__ == "__main__":
    main()
