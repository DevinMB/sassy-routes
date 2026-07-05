from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """12-factor config: everything comes from APEX_* env vars."""

    model_config = SettingsConfigDict(env_prefix="APEX_")

    graphhopper_url: str = "http://graphhopper:8989"
    # Flexible (LM) fun-dial routes are slower than CH; allow headroom.
    graphhopper_timeout_s: float = 30.0

    # Comma-separated allowed browser origins (CORS).
    allowed_origins: str = "http://localhost:8080"

    # Straight-line origin→destination cap. An unbounded request area is a
    # routing-engine DoS vector (CLAUDE-ref §7) — clamp it hard here.
    max_route_distance_km: float = 500.0

    # Geocoding (search box). Default is the public Photon instance (OSM data,
    # autocomplete-friendly fair use); point at a self-hosted Photon to go
    # fully self-contained. Results are biased toward the map's home region.
    geocoder_url: str = "https://photon.komoot.io"
    geocoder_timeout_s: float = 5.0
    geocode_bias_lat: float = 43.9
    geocode_bias_lng: float = -84.8

    # Segment fun scores + route cache. None disables both (routing still works).
    couchdb_url: str | None = None
    couchdb_timeout_s: float = 3.0

    # scoring.yaml location (mounted read-only in the container).
    scoring_path: str = "/srv/scoring.yaml"

    log_level: str = "INFO"

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()
