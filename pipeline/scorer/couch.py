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

    def put_seek_view(self, min_fun: float) -> None:
        """Index high-fun segments by grid cell, for corridor peak-seeking.

        The threshold is baked into the map function (CouchDB views are JS), so
        it's generated from scoring.yaml rather than hardcoded — guardrail 5.
        """
        design = {
            "_id": "_design/seek",
            "views": {
                "by_cell": {
                    "map": (
                        "function(doc){"
                        f"if(doc.type==='segment'&&doc.cell&&doc.fun_index>={min_fun}){{"
                        "emit(doc.cell,{fun:doc.fun_index,mid:doc.mid,"
                        "name:doc.name,length_m:doc.length_m,highway:doc.highway});"
                        "}}"
                    )
                }
            },
        }
        resp = self._client.put(f"/{self._db}/_design/seek", json=design)
        resp.raise_for_status()
        # build the index now so the first user request isn't the one that waits
        self._client.get(f"/{self._db}/_design/seek/_view/by_cell", params={"limit": 1})
        logger.info("seek view ready (min_fun=%s)", min_fun)

    def bulk(self, docs: list[dict]) -> None:
        if not docs:
            return
        resp = self._client.post(f"/{self._db}/_bulk_docs", json={"docs": docs})
        resp.raise_for_status()
        conflicts = [r for r in resp.json() if "error" in r]
        if conflicts:
            logger.warning("bulk write: %d errored docs (first: %s)", len(conflicts), conflicts[0])
