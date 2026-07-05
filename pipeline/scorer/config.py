import os

import yaml

# Highways we score (car-routable). Links inherit their parent class score.
CAR_HIGHWAYS = {
    "motorway", "motorway_link", "trunk", "trunk_link", "primary",
    "primary_link", "secondary", "secondary_link", "tertiary", "tertiary_link",
    "unclassified", "residential", "living_street", "service", "road",
}


def load_scoring() -> dict:
    path = os.environ.get("APEX_SCORING_PATH", "/srv/scoring.yaml")
    with open(path) as fh:
        return yaml.safe_load(fh)


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)
