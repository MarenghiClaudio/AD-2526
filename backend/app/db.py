"""
Connection pooling per PostgreSQL.

Due pool separati:
  _write_pool  → primary (scritture + letture coerenti post-write)
  _read_pool   → replica in streaming replication (letture pure)

Se `db_read_host` è vuoto, _read_pool non viene inizializzato e
`get_read_db()` preleva connessioni dal write pool (backward compat).

FastAPI esegue le route sincrone in un threadpool (ogni richiesta su un
thread separato), quindi si usa ThreadedConnectionPool per entrambi i pool.
"""

import logging
from contextlib import contextmanager
from typing import Iterator

import psycopg2
from psycopg2.extensions import connection as Connection
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from .config import get_settings

logger = logging.getLogger(__name__)

_write_pool: ThreadedConnectionPool | None = None
_read_pool: ThreadedConnectionPool | None = None


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
    """Inizializza write pool (e read pool se db_read_host è configurato)."""
    global _write_pool, _read_pool
    s = get_settings()

    if _write_pool is None:
        _write_pool = _make_pool(
            s.db_pool_min_conn, s.db_pool_max_conn,
            s.db_host, s.db_port, s.db_name, s.db_user, s.db_password,
        )
        logger.info(
            "Write pool inizializzato (min=%d, max=%d, host=%s)",
            s.db_pool_min_conn, s.db_pool_max_conn, s.db_host,
        )

    if _read_pool is None and s.db_read_host:
        _read_pool = _make_pool(
            s.db_read_pool_min_conn, s.db_read_pool_max_conn,
            s.db_read_host, s.db_read_port, s.db_name, s.db_user, s.db_password,
        )
        logger.info(
            "Read pool inizializzato (min=%d, max=%d, host=%s)",
            s.db_read_pool_min_conn, s.db_read_pool_max_conn, s.db_read_host,
        )
    elif _read_pool is None:
        logger.info("db_read_host non configurato: letture sul write pool (primary)")


def close_pool() -> None:
    """Chiude entrambi i pool."""
    global _write_pool, _read_pool
    if _write_pool is not None:
        _write_pool.closeall()
        _write_pool = None
        logger.info("Write pool chiuso")
    if _read_pool is not None:
        _read_pool.closeall()
        _read_pool = None
        logger.info("Read pool chiuso")


@contextmanager
def _acquire(pool: ThreadedConnectionPool) -> Iterator[Connection]:
    """Acquisisce una connessione dal pool con search_path impostato."""
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


@contextmanager
def get_connection() -> Iterator[Connection]:
    """Connessione dal write pool (primary). Per uso diretto fuori da FastAPI."""
    if _write_pool is None:
        raise RuntimeError("DB pool non inizializzato; chiama init_pool() prima")
    with _acquire(_write_pool) as conn:
        yield conn


def get_db() -> Iterator[Connection]:
    """
    Dependency FastAPI → write pool (primary).
    Usare per POST / PUT / DELETE e per le re-letture dei write hook.
    """
    if _write_pool is None:
        raise RuntimeError("DB pool non inizializzato; chiama init_pool() prima")
    with _acquire(_write_pool) as conn:
        yield conn


def get_read_db() -> Iterator[Connection]:
    """
    Dependency FastAPI → read pool (replica).
    Se la replica non è configurata, fallback sul write pool (primary).
    Usare per GET e per le letture pure nelle strategy.
    """
    pool = _read_pool if _read_pool is not None else _write_pool
    if pool is None:
        raise RuntimeError("DB pool non inizializzato; chiama init_pool() prima")
    with _acquire(pool) as conn:
        yield conn
