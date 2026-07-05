"""Minimal SRTM3 (90 m) elevation sampler.

Downloads .hgt.zip tiles on demand from the Kurviger SRTM mirror (the same
source GraphHopper uses), caches them on disk, and samples with bilinear
interpolation. Elevation failures are never fatal — callers get None and
score elevation as zero.
"""
import io
import logging
import math
import zipfile
from pathlib import Path

import httpx
import numpy as np

logger = logging.getLogger("scorer.srtm")

TILE_URL = "https://srtm.kurviger.de/SRTM3/North_America/{name}.hgt.zip"
SAMPLES = 1201  # SRTM3: 1201x1201 grid, 3 arc-seconds
VOID = -32768


class SrtmSampler:
    def __init__(self, cache_dir: str):
        self._cache = Path(cache_dir)
        self._cache.mkdir(parents=True, exist_ok=True)
        self._tiles: dict[tuple[int, int], np.ndarray | None] = {}
        self._client = httpx.Client(timeout=60, follow_redirects=True)

    def elevations(self, lats: np.ndarray, lngs: np.ndarray) -> np.ndarray | None:
        """Bilinear-sampled elevations in meters; None if any tile is missing."""
        out = np.empty(len(lats))
        for i, (lat, lng) in enumerate(zip(lats, lngs)):
            tile = self._tile(math.floor(lat), math.floor(lng))
            if tile is None:
                return None
            # row 0 is the tile's north edge
            y = (1.0 - (lat - math.floor(lat))) * (SAMPLES - 1)
            x = (lng - math.floor(lng)) * (SAMPLES - 1)
            y0, x0 = int(y), int(x)
            y1, x1 = min(y0 + 1, SAMPLES - 1), min(x0 + 1, SAMPLES - 1)
            fy, fx = y - y0, x - x0
            v = (
                tile[y0, x0] * (1 - fy) * (1 - fx)
                + tile[y0, x1] * (1 - fy) * fx
                + tile[y1, x0] * fy * (1 - fx)
                + tile[y1, x1] * fy * fx
            )
            out[i] = v
        return out

    def _tile(self, lat: int, lng: int) -> np.ndarray | None:
        key = (lat, lng)
        if key in self._tiles:
            return self._tiles[key]
        name = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lng >= 0 else 'W'}{abs(lng):03d}"
        hgt_path = self._cache / f"{name}.hgt"
        try:
            if not hgt_path.exists():
                resp = self._client.get(TILE_URL.format(name=name))
                resp.raise_for_status()
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    inner = next(n for n in zf.namelist() if n.lower().endswith(".hgt"))
                    hgt_path.write_bytes(zf.read(inner))
                logger.info("downloaded SRTM tile %s", name)
            raw = np.fromfile(hgt_path, dtype=">i2").astype(np.float64)
            grid = raw.reshape(SAMPLES, SAMPLES)
            # patch voids with the tile mean (rare in Michigan)
            voids = grid == VOID
            if voids.any():
                grid[voids] = grid[~voids].mean() if (~voids).any() else 0.0
            self._tiles[key] = grid
        except Exception as exc:  # noqa: BLE001 — degrade, don't die
            logger.warning("SRTM tile %s unavailable: %s", name, exc)
            self._tiles[key] = None
        return self._tiles[key]
