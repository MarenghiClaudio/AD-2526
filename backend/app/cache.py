"""
Redis client singleton — inizializzato al boot insieme al pool DB.
Usa decode_responses=True così i valori sono già str e non bytes.
"""

import logging
import redis
from .config import get_settings

logger = logging.getLogger(__name__)
_redis: redis.Redis | None = None


def is_cache_enabled() -> bool:
    return get_settings().cache_enabled


def init_redis() -> None:
    if not is_cache_enabled():
        logger.info("Cache disabled — skipping Redis init")
        return
    global _redis
    s = get_settings()
    _redis = redis.Redis(
        host=s.redis_host,
        port=s.redis_port,
        db=s.redis_db,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    _redis.ping()
    logger.info("Redis connected (%s:%d db=%d)", s.redis_host, s.redis_port, s.redis_db)


def close_redis() -> None:
    global _redis
    if _redis:
        _redis.close()
        _redis = None
        logger.info("Redis closed")


def get_redis() -> redis.Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialized; call init_redis() first")
    return _redis