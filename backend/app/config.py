"""
Configurazione applicativa.

Tutti i parametri sono letti da variabili d'ambiente / .env tramite
pydantic-settings, così il codice non contiene mai valori magici e i
benchmark di Fase 2/3 si lanciano cambiando solo il .env.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Database (write — primary) ---
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "ad"
    db_user: str = "postgres"
    db_password: str = ""
    db_schema: str = "ad"
    db_pool_min_conn: int = 2
    db_pool_max_conn: int = 20

    # --- Database (read — replica) ---
    # Se db_read_host è vuoto il backend usa il primary anche per le letture
    # (comportamento identico a prima dell'introduzione della replica).
    db_read_host: str = ""
    db_read_port: int = 5432
    db_read_pool_min_conn: int = 2
    db_read_pool_max_conn: int = 20

    # --- FYP ranking ---
    fyp_weight_recency: float = 1.0
    fyp_weight_affinity: float = 2.0
    fyp_weight_popularity: float = 0.5
    fyp_recency_tau_hours: float = 24.0
    fyp_recency_window_days: int = 30
    fyp_affinity_direct: float = 1.0
    fyp_affinity_fof: float = 0.1
    fyp_default_limit: int = 50
    fyp_max_limit: int = 200

    # --- Redis (Fase 2: caching layer) ---
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""
    redis_pool_max_conn: int = 50

    # Strategia di caching attiva. Deve combaciare con una chiave di
    # `app/strategies/__init__.py::STRATEGIES`. Valori built-in:
    #   - "no_cache"     → baseline Fase 1, bypassa Redis
    #   - "cache_aside"  → lazy loading + TTL (default)
    # I compagni aggiungeranno qui le loro strategy.
    cache_strategy: str = "cache_aside"

    # TTL per tipo di chiave (secondi). Usato dalle strategy che si basano
    # su TTL (cache_aside, write_through, ecc.).
    cache_ttl_user: int = 300
    cache_ttl_post: int = 300
    cache_ttl_timeline: int = 60
    cache_ttl_feed: int = 60
    cache_ttl_feed_fof: int = 60

    # --- HTTP server ---
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # --- Logging ---
    request_log_path: str = "requests.log"
    log_level: str = "INFO"

    @property
    def fyp_recency_tau_seconds(self) -> float:
        return self.fyp_recency_tau_hours * 3600.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
