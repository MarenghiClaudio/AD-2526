"""
Connection pooling per PostgreSQL.

Si usa psycopg2.pool.ThreadedConnectionPool perché FastAPI esegue le route
sincrone in un threadpool (ogni richiesta sta su un thread separato).
Le connessioni vengono prese al boundary HTTP via dependency injection.
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

_pool: ThreadedConnectionPool | None = None


def init_pool() -> None:
    """Inizializza il pool al boot dell'app (chiamato da main.py)."""
    global _pool
    if _pool is not None:
        return
    s = get_settings()
    _pool = ThreadedConnectionPool(
        minconn=s.db_pool_min_conn,
        maxconn=s.db_pool_max_conn,
        host=s.db_host,
        port=s.db_port,
        dbname=s.db_name,
        user=s.db_user,
        password=s.db_password,
        cursor_factory=RealDictCursor,
    )
    logger.info(
        "DB pool initialized (min=%d, max=%d, host=%s, db=%s)",
        s.db_pool_min_conn,
        s.db_pool_max_conn,
        s.db_host,
        s.db_name,
    )


def close_pool() -> None:
    """Chiude tutte le connessioni del pool (chiamato allo shutdown)."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("DB pool closed")


@contextmanager
def get_connection() -> Iterator[Connection]:
    """
    Acquisisce una connessione dal pool con search_path già impostato.
    Commit automatico su successo, rollback su eccezione.
    """
    if _pool is None:
        raise RuntimeError("DB pool not initialized; call init_pool() first")

    conn = _pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {get_settings().db_schema}")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


def get_db() -> Iterator[Connection]:
    """
    Dependency FastAPI: yield una connessione gestita dal context manager.
    Uso negli endpoint: `db: Connection = Depends(get_db)`.
    """
    with get_connection() as conn:
        yield conn
