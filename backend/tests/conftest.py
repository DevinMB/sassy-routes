import os
from pathlib import Path

# Must be set before app.main is imported (settings load at import time).
os.environ.setdefault("APEX_SCORING_PATH", str(Path(__file__).parents[2] / "scoring.yaml"))
os.environ.setdefault("APEX_COUCHDB_URL", "http://couch.test:5984")
