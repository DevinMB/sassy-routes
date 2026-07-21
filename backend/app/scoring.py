"""scoring.yaml access + per-lambda GraphHopper custom model construction."""
import hashlib
from functools import lru_cache

import yaml

from .config import settings


@lru_cache(maxsize=1)
def scoring() -> dict:
    # Cached for the process lifetime: editing scoring.yaml needs a backend
    # restart to take effect (and see fingerprint() — cached routes carry it,
    # so a config change can never be served from a stale cache).
    with open(settings.scoring_path) as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=1)
def fingerprint() -> str:
    """Short hash of the scoring config, for cache keys.

    Keying on `version` alone was a trap: tuning any threshold without
    remembering to bump it served stale cached routes that silently ignored
    the change (cost real debugging time). Hashing the file makes staleness
    impossible to forget.
    """
    with open(settings.scoring_path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:10]


def custom_model_for(lam: float, cfg: dict) -> dict:
    """Priority-only custom model for fun dial λ.

    Effective factor = 1 - λ·(1 - factor): λ=0 → no effect, λ=1 → full penalty.
    Factors stay ≤ 1 (penalize boring/dangerous, never reward) — required for
    landmark admissibility and guardrail 4.
    """
    gcfg = cfg["gh_custom_model"]
    rules = [
        {"if": rule["condition"], "multiply_by": round(1.0 - lam * (1.0 - rule["factor"]), 4)}
        for rule in gcfg["priority"]
    ]
    rules += [{"if": rule["condition"], "multiply_by": rule["factor"]} for rule in gcfg["always"]]
    return {"priority": rules}
