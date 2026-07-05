"""Best-effort CouchDB access: segment fun scores + route cache.

Everything here degrades gracefully — routing must keep working with CouchDB
down (same spirit as guardrail 3 for Kafka). Failures log and return None/{}.
"""
import logging
import time

import httpx

logger = logging.getLogger("apex.couch")


class CouchClient:
    def __init__(self, url: str | None, timeout_s: float):
        self._client = httpx.Client(base_url=url, timeout=timeout_s) if url else None
        self._cache_db_ready = False

    def segment_fun(self, way_ids: list[int]) -> dict[int, float] | None:
        """way_id → fun_index. None = CouchDB unavailable (≠ empty result)."""
        if self._client is None or not way_ids:
            return None if self._client is None else {}
        try:
            resp = self._client.post(
                "/segments/_all_docs",
                params={"include_docs": "true"},
                json={"keys": [f"way:{wid}" for wid in way_ids]},
            )
            resp.raise_for_status()
            out: dict[int, float] = {}
            for row in resp.json().get("rows", []):
                doc = row.get("doc")
                if doc and "fun_index" in doc:
                    out[int(row["key"].removeprefix("way:"))] = doc["fun_index"]
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("segment lookup failed (degrading, fun_index=null): %s", exc)
            return None

    def cache_get(self, key: str) -> dict | None:
        if self._client is None:
            return None
        try:
            resp = self._client.get(f"/route_cache/{key}")
            if resp.status_code != 200:
                return None
            doc = resp.json()
            if doc.get("expires", 0) < time.time():
                return None
            return doc.get("payload")
        except Exception:  # noqa: BLE001
            return None

    def cache_put(self, key: str, payload: dict, ttl_s: int) -> None:
        if self._client is None:
            return
        try:
            if not self._cache_db_ready:
                self._client.put("/route_cache")  # 201 created / 412 exists
                self._cache_db_ready = True
            doc = {"payload": payload, "expires": time.time() + ttl_s}
            resp = self._client.put(f"/route_cache/{key}", json=doc)
            if resp.status_code == 409:  # expired doc left behind: take over
                rev = self._client.get(f"/route_cache/{key}").json().get("_rev")
                self._client.put(f"/route_cache/{key}", params={"rev": rev}, json=doc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("route cache write failed (ignored): %s", exc)
