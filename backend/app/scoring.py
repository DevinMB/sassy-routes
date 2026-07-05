"""scoring.yaml access + per-lambda GraphHopper custom model construction."""
from functools import lru_cache

import yaml

from .config import settings


@lru_cache(maxsize=1)
def scoring() -> dict:
    with open(settings.scoring_path) as fh:
        return yaml.safe_load(fh)


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
