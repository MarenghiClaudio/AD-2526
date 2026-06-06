"""
Dependency FastAPI: istanzia la strategy attiva e costruisce un
`StrategyContext` per la singola request.

La strategy concreta è una singleton per processo (immutable, no state),
quindi viene cachata con functools.lru_cache. Lo `StrategyContext` invece
si costruisce ad ogni request perché embed connection, timer e cache
service che sono per-richiesta.

Read/write routing:
  - GET, HEAD, OPTIONS → connessione dalla replica (round-robin)
  - POST, PUT, PATCH, DELETE → connessione al master
  Questo avviene in modo trasparente: le strategy continuano a usare
  ctx.conn senza sapere su quale nodo stanno girando.
  Se DB_HOSTS_READ è vuoto (sviluppo locale), entrambi i path usano il master.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Iterator

import redis
from fastapi import Depends, Request

from ..cache import CacheService, get_cache_client
from ..config import Settings, get_settings
from ..core.request_state import start_timing
from ..db import get_read_connection, get_write_connection
from . import get_strategy
from .base import CacheStrategy, StrategyContext

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@lru_cache(maxsize=1)
def _active_strategy(name: str) -> CacheStrategy:
    return get_strategy(name)


def get_active_strategy(
    settings: Settings = Depends(get_settings),
) -> CacheStrategy:
    """Dependency: istanza singleton della strategy configurata in .env."""
    return _active_strategy(settings.cache_strategy)


def get_request_context(
    request: Request,
    redis_client: redis.Redis = Depends(get_cache_client),
    settings: Settings = Depends(get_settings),
) -> Iterator[StrategyContext]:
    """
    Dependency: costruisce il context per la request corrente.
    Sceglie la connessione DB in base al metodo HTTP:
      - scritture (POST/PUT/PATCH/DELETE) → master
      - letture (GET/...) → replica round-robin (o master se non configurato)
    """
    conn_ctx = (
        get_write_connection()
        if request.method in _MUTATING_METHODS
        else get_read_connection()
    )
    with conn_ctx as conn:
        rt = start_timing(request)
        cache = CacheService(redis_client, rt, enabled=True)
        yield StrategyContext(conn=conn, cache=cache, db_timer=rt.db, settings=settings)
