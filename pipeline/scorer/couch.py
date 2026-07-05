import logging

import httpx

logger = logging.getLogger("scorer.couch")


class CouchWriter:
    def __init__(self, base_url: str, db: str):
        self._db = db
        self._client = httpx.Client(base_url=base_url, timeout=60)

    def recreate_db(self) -> None:
        """Full rebuild each run: drop and recreate (pipeline is the only writer)."""
        resp = self._client.delete(f"/{self._db}")
        if resp.status_code not in (200, 404):
            resp.raise_for_status()
        self._client.put(f"/{self._db}").raise_for_status()
        logger.info("recreated db %s", self._db)

    def bulk(self, docs: list[dict]) -> None:
        if not docs:
            return
        resp = self._client.post(f"/{self._db}/_bulk_docs", json={"docs": docs})
        resp.raise_for_status()
        conflicts = [r for r in resp.json() if "error" in r]
        if conflicts:
            logger.warning("bulk write: %d errored docs (first: %s)", len(conflicts), conflicts[0])
