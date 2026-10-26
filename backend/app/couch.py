"""Best-effort CouchDB access: segment fun scores + route cache.

Everything here degrades gracefully — routing must keep working with CouchDB
down (same spirit as guardrail 3 for Kafka). Failures log and return None/{}.
"""
import logging
import time

from urllib.parse import unquote, urlsplit, urlunsplit

import httpx

logger = logging.getLogger("apex.couch")


def split_credentials(url: str) -> tuple[str, tuple[str, str] | None]:
    """Move user:password out of a CouchDB URL into httpx basic auth.

    httpx logs every request URL at INFO; with the credentials in the base URL
    that put the CouchDB password in the logs. Kept separate, no URL carries it.
    """
    parts = urlsplit(url)
    if not parts.username:
        return url, None
    host = parts.hostname or ""
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit(parts._replace(netloc=netloc)), (unquote(parts.username), unquote(parts.password or ""))


class CouchClient:
    def __init__(self, url: str | None, timeout_s: float):
        self._client = None
        if url:
            base, auth = split_credentials(url)
            self._client = httpx.Client(base_url=base, auth=auth, timeout=timeout_s)
        self._cache_db_ready = False

    def segment_docs(self, way_ids: list[int]) -> dict[int, dict] | None:
        """way_id → scored segment doc (fun_index, components, gates).

        None = CouchDB unavailable (≠ empty result). Callers get the whole doc
        so the API can explain *why* a route scored what it did, not just the
        final number — same query cost, we were already fetching full docs.
        """
        if self._client is None or not way_ids:
            return None if self._client is None else {}
        try:
            resp = self._client.post(
                "/segments/_all_docs",
                params={"include_docs": "true"},
                json={"keys": [f"way:{wid}" for wid in way_ids]},
            )
            resp.raise_for_status()
            out: dict[int, dict] = {}
            for row in resp.json().get("rows", []):
                doc = row.get("doc")
                if doc and "fun_index" in doc:
                    out[int(row["key"].removeprefix("way:"))] = doc
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("segment lookup failed (degrading, fun_index=null): %s", exc)
            return None

    def seek_rows(self, cells: list[list[int]]) -> list[dict]:
        """High-fun segments in the given grid cells (seek/by_cell view).

        Best-effort like everything else here: on failure we return nothing and
        the caller simply skips peak-seeking.
        """
        if self._client is None or not cells:
            return []
        try:
            resp = self._client.post(
                "/segments/_design/seek/_view/by_cell", json={"keys": cells}
            )
            if resp.status_code != 200:
                logger.warning("seek view unavailable (%s) — skipping", resp.status_code)
                return []
            return resp.json().get("rows", [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("seek lookup failed (skipping): %s", exc)
            return []

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
