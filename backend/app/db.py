"""
Connection pooling per PostgreSQL.

Si usa psycopg2.pool.ThreadedConnectionPool perché FastAPI esegue le route
sincrone in un threadpool (ogni richiesta sta su un thread separato).

Pool:
  _write_pool  → VM master (scritture + letture quando non ci sono repliche)
  _read_pools  → lista di pool sulle repliche (letture, round-robin)

Se DB_HOSTS_READ è vuoto, get_read_connection() ricade su _write_pool
in modo trasparente: il codice funziona identico in locale (single-node).
"""

import logging
import os
import threading
from contextlib import contextmanager
from typing import Iterator

import psycopg2
from psycopg2.extensions import connection as Connection
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from .config import get_settings

logger = logging.getLogger(__name__)

_write_pool: ThreadedConnectionPool | None = None
_read_pools: list[ThreadedConnectionPool] = []
_read_counter: int = 0
_read_lock = threading.Lock()

# Semaforo per pool: rende l'acquisizione di una connessione *bloccante*.
# ThreadedConnectionPool.getconn() lancia PoolError appena il pool è pieno;
# con un semaforo inizializzato a maxconn i thread in eccesso ATTENDONO una
# connessione libera invece di fallire con 500. Questo trasforma la
# saturazione del DB in degradazione di latenza (richieste in coda), che è il
# comportamento corretto per misurare il DB come bottleneck.
_pool_semaphores: dict[int, threading.Semaphore] = {}

# Timeout massimo di attesa per una connessione. Se scade, la richiesta
# fallisce davvero (il DB non riesce a smaltire la coda): saturazione genuina.
_ACQUIRE_TIMEOUT = float(os.getenv("DB_POOL_ACQUIRE_TIMEOUT", "30"))


def _make_pool(host: str, min_conn: int, max_conn: int) -> ThreadedConnectionPool:
    s = get_settings()
    pool = ThreadedConnectionPool(
        minconn=min_conn,
        maxconn=max_conn,
        host=host,
        port=s.db_port,
        dbname=s.db_name,
        user=s.db_user,
        password=s.db_password,
        cursor_factory=RealDictCursor,
    )
    _pool_semaphores[id(pool)] = threading.Semaphore(max_conn)
    return pool


def init_pool() -> None:
    """Inizializza il pool di scrittura (master) al boot."""
    global _write_pool
    if _write_pool is not None:
        return
    s = get_settings()
    _write_pool = _make_pool(s.db_host, s.db_pool_min_conn, s.db_pool_max_conn)
    logger.info(
        "Write pool initialized (min=%d, max=%d, host=%s)",
        s.db_pool_min_conn, s.db_pool_max_conn, s.db_host,
    )


def init_read_pools() -> None:
    """Inizializza un pool per ogni replica (DB_HOSTS_READ). No-op se vuoto."""
    global _read_pools
    s = get_settings()
    hosts = s.db_read_hosts
    if not hosts:
        logger.info("No DB_HOSTS_READ configured — reads will use the write pool.")
        return
    _read_pools = [_make_pool(h, 1, s.db_pool_max_conn) for h in hosts]
    logger.info("Read pools initialized: %s", hosts)


def close_pool() -> None:
    """Chiude il pool di scrittura."""
    global _write_pool
    if _write_pool is not None:
        _pool_semaphores.pop(id(_write_pool), None)
        _write_pool.closeall()
        _write_pool = None
        logger.info("Write pool closed")


def close_read_pools() -> None:
    """Chiude tutti i pool di lettura."""
    global _read_pools
    for pool in _read_pools:
        _pool_semaphores.pop(id(pool), None)
        pool.closeall()
    _read_pools = []
    logger.info("Read pools closed")


def _next_read_pool() -> ThreadedConnectionPool:
    """Seleziona il prossimo pool di lettura in round-robin (thread-safe)."""
    global _read_counter
    with _read_lock:
        pool = _read_pools[_read_counter % len(_read_pools)]
        _read_counter += 1
    return pool


@contextmanager
def _conn_from(pool: ThreadedConnectionPool) -> Iterator[Connection]:
    """Acquisisce una connessione dal pool dato, con commit/rollback automatico.

    L'acquisizione è bloccante: se il pool è pieno il thread attende (fino a
    _ACQUIRE_TIMEOUT) che una connessione si liberi, invece di fallire subito
    con PoolError. Così la saturazione si manifesta come latenza, non come 500.
    """
    sem = _pool_semaphores.get(id(pool))
    if sem is not None and not sem.acquire(timeout=_ACQUIRE_TIMEOUT):
        raise psycopg2.pool.PoolError(
            f"timeout ({_ACQUIRE_TIMEOUT}s) in attesa di una connessione dal pool"
        )
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
        if sem is not None:
            sem.release()


@contextmanager
def get_write_connection() -> Iterator[Connection]:
    """Connessione al master (scritture)."""
    if _write_pool is None:
        raise RuntimeError("Write pool not initialized; call init_pool() first")
    with _conn_from(_write_pool) as conn:
        yield conn


@contextmanager
def get_read_connection() -> Iterator[Connection]:
    """
    Connessione a una replica in round-robin (letture).
    Ricade sul master se nessuna replica è configurata.
    """
    if _write_pool is None:
        raise RuntimeError("Write pool not initialized; call init_pool() first")
    pool = _next_read_pool() if _read_pools else _write_pool
    with _conn_from(pool) as conn:
        yield conn


# Alias per backward-compatibility (usato in test e script standalone)
@contextmanager
def get_connection() -> Iterator[Connection]:
    with get_write_connection() as conn:
        yield conn


def get_db() -> Iterator[Connection]:
    """Dependency FastAPI legacy: yield connessione di scrittura."""
    with get_write_connection() as conn:
        yield conn
