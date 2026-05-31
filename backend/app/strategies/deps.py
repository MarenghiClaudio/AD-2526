"""
Dependency FastAPI: istanzia la strategy attiva e costruisce un
`StrategyContext` per la singola request.

La strategy concreta è una singleton per processo (immutable, no state),
quindi viene cachata con functools.lru_cache. Lo `StrategyContext` invece
si costruisce ad ogni request perché embed connection, timer e cache
service che sono per-richiesta.
"""

from functools import lru_cache

import redis
from fastapi import Depends, Request
from psycopg2.extensions import connection as Connection

from ..cache import CacheService, get_cache_client
from ..config import Settings, get_settings
from ..core.request_state import start_timing
from ..db import get_db, get_read_db
from . import get_strategy
from .base import CacheStrategy, StrategyContext


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
    db: Connection = Depends(get_db),
    db_read: Connection = Depends(get_read_db),
    redis_client: redis.Redis = Depends(get_cache_client),
    settings: Settings = Depends(get_settings),
) -> StrategyContext:
    """
    Dependency: costruisce il context per la request corrente.

    db      → write pool (primary): scritture e write-hook re-reads
    db_read → read pool (replica, o primary se non configurata): letture pure
    """
    rt = start_timing(request)
    cache = CacheService(redis_client, rt, enabled=True)
    return StrategyContext(
        conn=db,
        read_conn=db_read,
        cache=cache,
        db_timer=rt.db,
        settings=settings,
    )
