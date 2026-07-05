"""Analytics/audit event emission.

Phase 3 replaces LogEventEmitter with a Kafka producer on topic `apex.events`.
Two invariants that must survive that swap (CLAUDE-ref §6, guardrail 3):
  - emit() is fire-and-forget and NEVER raises into the request path;
  - every event carries `user_id` (nullable until the auth phase).
"""
import json
import logging
import time
from typing import Any, Protocol

logger = logging.getLogger("apex.events")


class EventEmitter(Protocol):
    def emit(self, event_type: str, payload: dict[str, Any]) -> None: ...


class LogEventEmitter:
    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        try:
            logger.info(json.dumps({
                "event_type": event_type,
                "ts": time.time(),
                "user_id": None,  # populated once the auth phase exists
                **payload,
            }))
        except Exception:  # noqa: BLE001 — never let analytics break routing
            logger.exception("event emission failed (ignored)")
