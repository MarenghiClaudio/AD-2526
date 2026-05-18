"""
Redis caching layer.

Componenti:
  * pool di connessioni Redis (singleton, init/close nel lifespan)
  * `CacheService`: wrapper sopra `redis.Redis` che misura il tempo speso
    e marca hit/miss su `RequestTiming`. Le repository non parlano mai
    direttamente con `redis.Redis` — passano sempre per il service.
  * helper di key building per evitare typo e centralizzare la convenzione

Strategia (Fase 2 — Combinazione A, cache-aside):
  READ : cache.get → MISS → DB.query → cache.set(ttl) → return
  WRITE: DB.write → cache.delete(chiavi impattate)

Tutto sincrono, in linea con psycopg2 e con il pool di thread di FastAPI.
"""

from __future__ import annotations

import logging
from typing import Type, TypeVar

import redis
from pydantic import BaseModel, TypeAdapter

from .config import get_settings
from .core.timing import RequestTiming

logger = logging.getLogger(__name__)

_pool: redis.ConnectionPool | None = None

T = TypeVar("T", bound=BaseModel)

# Cache dei TypeAdapter per modello: la creazione di TypeAdapter compila
# il validator di Pydantic ed è costosa (decine di ms). Va fatta una volta
# per processo, non ad ogni richiesta.
_LIST_ADAPTERS: dict[Type[BaseModel], TypeAdapter] = {}


def _list_adapter(model_cls: Type[T]) -> TypeAdapter[list[T]]:
    adapter = _LIST_ADAPTERS.get(model_cls)
    if adapter is None:
        adapter = TypeAdapter(list[model_cls])  # type: ignore[valid-type]
        _LIST_ADAPTERS[model_cls] = adapter
    return adapter


# --- Connection pool lifecycle -------------------------------------------------


def init_pool() -> None:
    """Inizializza il pool Redis al boot dell'app."""
    global _pool
    if _pool is not None:
        return
    s = get_settings()
    _pool = redis.ConnectionPool(
        host=s.redis_host,
        port=s.redis_port,
        db=s.redis_db,
        password=s.redis_password or None,
        max_connections=s.redis_pool_max_conn,
        decode_responses=True,
    )
    # Smoke check: PING blocca se Redis non risponde.
    try:
        redis.Redis(connection_pool=_pool).ping()
    except redis.RedisError:
        logger.exception("Redis PING failed on init")
        raise
    logger.info(
        "Redis pool initialized (host=%s:%d db=%d max=%d)",
        s.redis_host,
        s.redis_port,
        s.redis_db,
        s.redis_pool_max_conn,
    )


def close_pool() -> None:
    """Rilascia tutte le connessioni Redis allo shutdown."""
    global _pool
    if _pool is not None:
        _pool.disconnect()
        _pool = None
        logger.info("Redis pool closed")


def _get_client() -> redis.Redis:
    if _pool is None:
        raise RuntimeError("Redis pool not initialized; call init_pool() first")
    return redis.Redis(connection_pool=_pool)


# --- Key builders --------------------------------------------------------------


class Keys:
    """Convenzioni dei nomi delle chiavi. Centralizzate per evitare typo."""

    @staticmethod
    def user(user_id: int) -> str:
        return f"user:{user_id}"

    @staticmethod
    def post(post_id: int) -> str:
        return f"post:{post_id}"

    @staticmethod
    def timeline(viewer_id: int, limit: int) -> str:
        return f"timeline:{viewer_id}:{limit}"

    @staticmethod
    def fyp(viewer_id: int, limit: int) -> str:
        return f"fyp:{viewer_id}:{limit}"

    @staticmethod
    def fyp_fof(viewer_id: int, limit: int) -> str:
        return f"fyp_fof:{viewer_id}:{limit}"


# --- CacheService --------------------------------------------------------------


class CacheService:
    """
    Wrapper di Redis pensato per i benchmark:
      * misura il tempo speso in Redis aggiornando `timing.cache`
      * marca `timing.cache_hit` sulla PRIMA get_* della request
      * `enabled=False` → fa passare tutte le get come MISS, tutte le set/delete
        come no-op → permette di tornare alla baseline Fase 1 senza rimuovere
        il codice (basta `CACHE_ENABLED=false` nel .env)

    Le repository chiamano:
        cached = cache.get_model(key, Model)
        if cached is not None: return cached
        ...query DB...
        cache.set_model(key, model_instance, ttl)
    """

    def __init__(
        self,
        client: redis.Redis,
        timing: RequestTiming,
        enabled: bool = True,
    ) -> None:
        self._client = client
        self._timing = timing
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    # --- single objects ---

    def get_model(self, key: str, model_cls: Type[T]) -> T | None:
        if not self._enabled:
            self._record_hit(False)
            return None
        with self._timing.cache.measure():
            raw = self._client.get(key)
        self._record_hit(raw is not None)
        if raw is None:
            return None
        return model_cls.model_validate_json(raw)

    def set_model(self, key: str, value: BaseModel, ttl: int) -> None:
        if not self._enabled:
            return
        payload = value.model_dump_json()
        with self._timing.cache.measure():
            self._client.setex(key, ttl, payload)

    # --- lists of objects ---

    def get_model_list(self, key: str, model_cls: Type[T]) -> list[T] | None:
        if not self._enabled:
            self._record_hit(False)
            return None
        with self._timing.cache.measure():
            raw = self._client.get(key)
        self._record_hit(raw is not None)
        if raw is None:
            return None
        return _list_adapter(model_cls).validate_json(raw)

    def set_model_list(self, key: str, values: list[BaseModel], ttl: int) -> None:
        if not self._enabled:
            return
        # Pydantic serializza ogni elemento singolarmente; lo facciamo in modo
        # uniforme con un piccolo wrapping json-array.
        items_json = "[" + ",".join(v.model_dump_json() for v in values) + "]"
        with self._timing.cache.measure():
            self._client.setex(key, ttl, items_json)

    # --- invalidation ---

    def delete(self, *keys: str) -> None:
        if not self._enabled or not keys:
            return
        with self._timing.cache.measure():
            self._client.delete(*keys)

    # --- internals ---

    def _record_hit(self, hit: bool) -> None:
        """
        Marca hit/miss della PRIMA cache lookup. Le successive non sovrascrivono
        (es. una get_post dentro fetch_feed non deve riclassificare il request).
        """
        if self._timing.cache_hit is None:
            self._timing.cache_hit = hit


# --- FastAPI dependency --------------------------------------------------------


def get_cache_client() -> redis.Redis:
    """Dependency: yield del client Redis dal pool (zero overhead)."""
    return _get_client()
