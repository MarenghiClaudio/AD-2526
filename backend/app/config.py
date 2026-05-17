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

    # --- Database ---
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "ad"
    db_user: str = "postgres"
    db_password: str = ""
    db_schema: str = "ad"
    db_pool_min_conn: int = 2
    db_pool_max_conn: int = 20

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

    # --- HTTP server ---
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # --- Logging ---
    request_log_path: str = "requests.log"
    log_level: str = "INFO"
    
    cache_enabled: bool = True
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_ttl_timeline: int = 60
    redis_ttl_fyp: int = 120
    redis_ttl_user_profile: int = 300

    @property
    def fyp_recency_tau_seconds(self) -> float:
        return self.fyp_recency_tau_hours * 3600.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
