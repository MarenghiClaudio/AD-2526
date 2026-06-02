"""
Connection pooling per PostgreSQL.

Due categorie di pool:
  _write_pool   → primary (scritture + re-letture nei write hook)
  _read_pools   → lista di repliche in streaming replication (letture pure)

Se db_read_hosts è vuoto, _read_pools è vuoto e get_read_db() fallback
sul write pool — comportamento identico a un setup senza replica.

Le letture sono distribuite round-robin tra le repliche disponibili
(thread-safe tramite lock).
"""

import logging
import threading
from contextlib import contextmanager
from typing import Iterator

from psycopg2.extensions import connection as Connection
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from .config import get_settings

logger = logging.getLogger(__name__)

_write_pool: ThreadedConnectionPool | None = None
_read_pools: list[ThreadedConnectionPool] = []
_rr_index: int = 0
_rr_lock = threading.Lock()


def _make_pool(
    minconn: int,
    maxconn: int,
    host: str,
    port: int,
    dbname: str,
    user: str,
    password: str,
) -> ThreadedConnectionPool:
    return ThreadedConnectionPool(
        minconn=minconn,
        maxconn=maxconn,
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        cursor_factory=RealDictCursor,
    )


def init_pool() -> None:
    """Inizializza write pool e tutti i read pool configurati."""
    global _write_pool, _read_pools
    s = get_settings()

    if _write_pool is None:
        _write_pool = _make_pool(
            s.db_pool_min_conn, s.db_pool_max_conn,
            s.db_host, s.db_port, s.db_name, s.db_user, s.db_password,
        )
        logger.info("Write pool inizializzato (host=%s)", s.db_host)

    if not _read_pools:
        hosts = s.db_read_host_list
        for host in hosts:
            pool = _make_pool(
                s.db_read_pool_min_conn, s.db_read_pool_max_conn,
                host, s.db_read_port, s.db_name, s.db_user, s.db_password,
            )
            _read_pools.append(pool)
            logger.info("Read pool inizializzato (host=%s)", host)

        if not hosts:
            logger.info("db_read_hosts non configurato: letture sul primary")


def close_pool() -> None:
    """Chiude write pool e tutti i read pool."""
    global _write_pool, _read_pools
    if _write_pool is not None:
        _write_pool.closeall()
        _write_pool = None
        logger.info("Write pool chiuso")
    for pool in _read_pools:
        pool.closeall()
    _read_pools.clear()
    if _read_pools is not None:
        logger.info("Read pool/s chiusi")


def _next_read_pool() -> ThreadedConnectionPool:
    """Seleziona il prossimo read pool in round-robin."""
    global _rr_index
    with _rr_lock:
        pool = _read_pools[_rr_index % len(_read_pools)]
        _rr_index += 1
    return pool


@contextmanager
def _acquire(pool: ThreadedConnectionPool) -> Iterator[Connection]:
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {get_settings().db_schema}")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def get_db() -> Iterator[Connection]:
    """Dependency FastAPI → write pool (primary)."""
    if _write_pool is None:
        raise RuntimeError("DB pool non inizializzato; chiama init_pool() prima")
    with _acquire(_write_pool) as conn:
        yield conn


def get_read_db() -> Iterator[Connection]:
    """
    Dependency FastAPI → read pool (round-robin tra le repliche).
    Fallback sul write pool se nessuna replica è configurata.
    """
    if _read_pools:
        with _acquire(_next_read_pool()) as conn:
            yield conn
    elif _write_pool is not None:
        with _acquire(_write_pool) as conn:
            yield conn
    else:
        raise RuntimeError("DB pool non inizializzato; chiama init_pool() prima")
