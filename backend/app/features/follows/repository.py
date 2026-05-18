"""
Repository per la feature follows.

Strategia Fase 2 — invalidazione su entrambi i profili coinvolti:
  POST   /follows → INSERT → DELETE user:{follower}, user:{followed}
  DELETE /follows → DELETE → DELETE user:{follower}, user:{followed}

Razionale: cambia following_count di chi inizia/smette di seguire e
follower_count di chi viene seguito/non seguito. I feed di chi cambia
le sue follow non vengono invalidati pro-attivamente (TTL gestisce).
"""

from psycopg2.extensions import connection as Connection

from ...cache import CacheService
from ...core.timing import Timer
from ..users import repository as users_repo


_INSERT_FOLLOW_SQL = """
INSERT INTO follows (follower_id, followed_id)
VALUES (%(fr)s, %(fd)s)
ON CONFLICT (follower_id, followed_id) DO NOTHING
"""

_DELETE_FOLLOW_SQL = """
DELETE FROM follows
WHERE follower_id = %(fr)s AND followed_id = %(fd)s
"""


def add_follow(
    conn: Connection,
    follower_id: int,
    followed_id: int,
    cache: CacheService,
    db_timer: Timer,
) -> bool:
    with db_timer.measure():
        with conn.cursor() as cur:
            cur.execute(_INSERT_FOLLOW_SQL, {"fr": follower_id, "fd": followed_id})
            created = cur.rowcount > 0
    if created:
        users_repo.invalidate(cache, follower_id, followed_id)
    return created


def remove_follow(
    conn: Connection,
    follower_id: int,
    followed_id: int,
    cache: CacheService,
    db_timer: Timer,
) -> bool:
    with db_timer.measure():
        with conn.cursor() as cur:
            cur.execute(_DELETE_FOLLOW_SQL, {"fr": follower_id, "fd": followed_id})
            deleted = cur.rowcount > 0
    if deleted:
        users_repo.invalidate(cache, follower_id, followed_id)
    return deleted
