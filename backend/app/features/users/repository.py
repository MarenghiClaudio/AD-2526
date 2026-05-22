"""
Data access per la feature users.

Solo SQL puro (psycopg2). La logica di caching vive nelle strategy
(`app/strategies/<strategy>.py`), che chiamano queste funzioni come
building block sul "MISS path" o per fallback.
"""

from psycopg2.extensions import connection as Connection

from ...core.timing import Timer
from .schemas import UserProfile


_USER_PROFILE_SQL = """
SELECT
    u.user_id,
    u.username,
    u.created_at,
    COALESCE(p.cnt, 0) AS post_count,
    COALESCE(fo.cnt, 0) AS follower_count,
    COALESCE(fi.cnt, 0) AS following_count
FROM users u
LEFT JOIN (
    SELECT user_id, COUNT(*) AS cnt FROM posts WHERE user_id = %(uid)s GROUP BY user_id
) p ON p.user_id = u.user_id
LEFT JOIN (
    SELECT followed_id, COUNT(*) AS cnt FROM follows WHERE followed_id = %(uid)s GROUP BY followed_id
) fo ON fo.followed_id = u.user_id
LEFT JOIN (
    SELECT follower_id, COUNT(*) AS cnt FROM follows WHERE follower_id = %(uid)s GROUP BY follower_id
) fi ON fi.follower_id = u.user_id
WHERE u.user_id = %(uid)s
"""


def query_user_profile(
    conn: Connection, user_id: int, db_timer: Timer
) -> UserProfile | None:
    """Profilo utente con counter aggregati (sola DB, no cache)."""
    with db_timer.measure():
        with conn.cursor() as cur:
            cur.execute(_USER_PROFILE_SQL, {"uid": user_id})
            row = cur.fetchone()
    if row is None:
        return None
    return UserProfile.model_validate(row)


def user_exists(conn: Connection, user_id: int, db_timer: Timer) -> bool:
    """
    Validation helper (sola DB). Usato dalle route prima di accettare una
    scrittura. Non passa mai per la cache: vogliamo lo stato corrente.
    """
    with db_timer.measure():
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
            return cur.fetchone() is not None
