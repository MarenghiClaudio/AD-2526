"""
Repository per la feature likes.

Strategia Fase 2 — l'invalidazione si limita a `post:{id}`:
  POST   /likes → INSERT ... ON CONFLICT DO NOTHING → DELETE post:{pid}
  DELETE /likes → DELETE                            → DELETE post:{pid}

Razionale: like_count fa parte dell'oggetto Post cachato. Cambia ad ogni
mutazione di like quindi va invalidato. I feed (timeline/fyp) non vengono
toccati pro-attivamente: lascio gestire dalla scadenza TTL (~60s). In un
social reale i feed non si re-rankano ad ogni singolo like; usare TTL è
una scelta esplicita di "consistency rilassata" da motivare nel report.
"""

from psycopg2.extensions import connection as Connection

from ...cache import CacheService
from ...core.timing import Timer
from ..posts import repository as posts_repo


_INSERT_LIKE_SQL = """
INSERT INTO likes (user_id, post_id)
VALUES (%(uid)s, %(pid)s)
ON CONFLICT (user_id, post_id) DO NOTHING
"""

_DELETE_LIKE_SQL = """
DELETE FROM likes
WHERE user_id = %(uid)s AND post_id = %(pid)s
"""

_POST_EXISTS_SQL = "SELECT 1 FROM posts WHERE post_id = %s"


def post_exists(conn: Connection, post_id: int, db_timer: Timer) -> bool:
    with db_timer.measure():
        with conn.cursor() as cur:
            cur.execute(_POST_EXISTS_SQL, (post_id,))
            return cur.fetchone() is not None


def add_like(
    conn: Connection,
    user_id: int,
    post_id: int,
    cache: CacheService,
    db_timer: Timer,
) -> bool:
    """True se è stato creato un nuovo like, False se già presente."""
    with db_timer.measure():
        with conn.cursor() as cur:
            cur.execute(_INSERT_LIKE_SQL, {"uid": user_id, "pid": post_id})
            created = cur.rowcount > 0
    if created:
        posts_repo.invalidate(cache, post_id)
    return created


def remove_like(
    conn: Connection,
    user_id: int,
    post_id: int,
    cache: CacheService,
    db_timer: Timer,
) -> bool:
    """True se è stata rimossa una riga, False se non c'era."""
    with db_timer.measure():
        with conn.cursor() as cur:
            cur.execute(_DELETE_LIKE_SQL, {"uid": user_id, "pid": post_id})
            deleted = cur.rowcount > 0
    if deleted:
        posts_repo.invalidate(cache, post_id)
    return deleted
