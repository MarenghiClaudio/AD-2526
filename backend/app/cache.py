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
            
    # ----------------------------------------------------------------------
    # 1. ZREVRANGE come lista di id (non model). Per il pattern "ZSET di id".
    # ----------------------------------------------------------------------

    def zrevrange_ids(self, key: str, end: int) -> list[int] | None:
        """
        ZREVRANGE key 0 end → lista di int (interpretati come post_id).

        Ritorna:
        - `None` se il sorted set non esiste (vero cache miss → rebuild)
        - `[]` se esiste ma è vuoto (HIT vuoto → niente da fare, NO rebuild)
        - `[id1, id2, ...]` ordinati per score DESC

        La distinzione None/[] è cruciale: un utente senza follow ha lo ZSET
        vuoto ma esistente (rebuild andato a buon fine, niente da mostrare).
        Non vogliamo rifare il rebuild ad ogni read in quel caso.

        Usa pipeline EXISTS+ZREVRANGE per tenere il round-trip a 1.
        """
        if not self._enabled:
            return None
        with self._timing.cache.measure():
            pipe = self._client.pipeline()
            pipe.exists(key)
            pipe.zrevrange(key, 0, end)
            exists, members = pipe.execute()

        if not exists:
            self._record_hit(False)
            return None

        self._record_hit(True)
        return [int(m) for m in members]


    # ----------------------------------------------------------------------
    # 2. ZADD bulk: popolamento iniziale di uno ZSET (cold rebuild).
    # ----------------------------------------------------------------------

    def zadd_bulk(self, key: str, id_score_map: dict[str, float], ttl: int) -> None:
        """
        ZADD massivo su una singola chiave + EXPIRE, in pipeline (1 round-trip).

        Uso tipico: rebuild di timeline:{viewer} dopo cold start, popolando
        da DB tutti i post_id rilevanti per il viewer.

        `id_score_map`: {member: score}. Tipicamente `{str(post_id): timestamp}`.
        """
        if not self._enabled or not id_score_map:
            return
        with self._timing.cache.measure():
            pipe = self._client.pipeline()
            pipe.zadd(key, id_score_map)
            pipe.expire(key, ttl)
            pipe.execute()


    # ----------------------------------------------------------------------
    # 3. Fan-out ZADD: un member, N chiavi (push_feed.on_post_created).
    # ----------------------------------------------------------------------

    def zadd_fanout(
        self,
        keys: list[str],
        member: str,
        score: float,
        ttl: int,
        max_size: int,
    ) -> None:
        """
        Fan-out di un singolo `member` su N sorted set.

        Per ogni chiave: ZCARD + ZADD + EXPIRE in una pipeline. Lo
        ZREMRANGEBYRANK (trim al max_size) viene eseguito SOLO sui set la
        cui cardinalità eccede max_size dopo lo ZADD — verificato dal valore
        di ritorno di ZCARD + ZADD.

        Costo dei comandi sul main-loop Redis:
        v1 push_feed:  3·N comandi sempre (ZADD + ZREMRANGEBYRANK + EXPIRE).
        qui:           3·N (ZCARD + ZADD + EXPIRE) + k·N (trim) con k ≪ 1.
                        In regime stazionario k = 0: solo quando il set
                        raggiunge max_size per la prima volta paga il trim.

        Two-stage pipeline (ZCARD/ZADD/EXPIRE → analisi → trim selettivo) è
        deliberato: ZADD ritorna 1/0 a seconda che abbia aggiunto un nuovo
        member, e usiamo questa info per calcolare card_dopo = card_prima + added.
        """
        if not self._enabled or not keys:
            return

        with self._timing.cache.measure():
            # Stage 1: ZCARD + ZADD + EXPIRE per ogni chiave
            stage1 = self._client.pipeline()
            for k in keys:
                stage1.zcard(k)
                stage1.zadd(k, {member: score})
                stage1.expire(k, ttl)
            results = stage1.execute()

            # results è [card0, added0, exp0, card1, added1, exp1, ...]
            to_trim: list[str] = []
            for idx, k in enumerate(keys):
                card_before = results[idx * 3]
                added = results[idx * 3 + 1]  # 1 se nuovo member, 0 se update
                if card_before + added > max_size:
                    to_trim.append(k)

            # Stage 2: trim solo dove necessario. In regime stazionario, skip.
            if to_trim:
                stage2 = self._client.pipeline()
                for k in to_trim:
                    # Tieni le ultime max_size voci (per score DESC).
                    # Rank negativo: -(max_size+1) lascia gli ultimi max_size.
                    stage2.zremrangebyrank(k, 0, -(max_size + 1))
                stage2.execute()


    # ----------------------------------------------------------------------
    # 4. MGET batch di model. Per il pattern "ZSET di id + MGET".
    # ----------------------------------------------------------------------

    def mget_models(self, keys: list[str], model_cls: type[T]) -> list[T | None]:
        """
        MGET batch → lista di model_cls. None nelle posizioni miss.

        Conserva l'ordine: output[i] corrisponde a keys[i]. Chi chiama può
        quindi sapere quali specifici id sono mancanti e fare fallback DB
        selettivo (vedi push_feed.fetch_timeline).

        Hit/miss accounting: registra HIT se almeno una chiave era presente.
        Semplificazione consapevole — per metriche granulari (hit ratio per
        feed completo) servirebbe esporre `found_count/total` al chiamante.
        """
        if not self._enabled or not keys:
            return [None] * len(keys)

        with self._timing.cache.measure():
            raw = self._client.mget(keys)

        found = sum(1 for r in raw if r is not None)
        self._record_hit(found > 0)

        return [
            model_cls.model_validate_json(r) if r is not None else None
            for r in raw
        ]


    # ----------------------------------------------------------------------
    # 5. SET batch di model. Per aggiornamenti multi-chiave in pipeline.
    # ----------------------------------------------------------------------

    def set_models(self, items: dict[str, BaseModel], ttl: int) -> None:
        """
        SETEX batch in pipeline. items = {key: model}, stesso ttl per tutti.

        Uso tipico: dopo un on_follow_* in write_through/push_feed, aggiornare
        sia `user:{follower}` sia `user:{followed}` in 1 round-trip Redis
        (anche se le query PG restano due separate).

        NB: Redis non ha un "MSETEX" nativo, ma una pipeline di N SETEX è
        equivalente in round-trip (1) e diretta da implementare.
        """
        if not self._enabled or not items:
            return
        with self._timing.cache.measure():
            pipe = self._client.pipeline()
            for key, model in items.items():
                pipe.setex(key, ttl, model.model_dump_json())
            pipe.execute()


    # ----------------------------------------------------------------------
    # 6. DELETE batch — alias leggibile per i sorted set.
    # ----------------------------------------------------------------------

    def delete_keys(self, *keys: str) -> None:
        """
        Alias di `self.delete(*keys)`. Esiste per leggibilità nelle strategy
        quando si invalida un sorted set (push_feed.on_follow_*). Se preferisci
        riusare direttamente `delete`, sostituisci le chiamate nei callsite
        e ometti questo metodo.
        """
        if not self._enabled or not keys:
            return
        with self._timing.cache.measure():
            self._client.delete(*keys)



# --- FastAPI dependency --------------------------------------------------------


def get_cache_client() -> redis.Redis:
    """Dependency: yield del client Redis dal pool (zero overhead)."""
    return _get_client()
