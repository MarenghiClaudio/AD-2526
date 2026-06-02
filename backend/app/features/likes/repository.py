"""
Data access per la feature likes.

Solo SQL puro. Le strategy reagiscono via on_like_added / on_like_removed.
"""

from psycopg2.extensions import connection as Connection

from ...core.timing import Timer


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


def insert_like(
    conn: Connection, user_id: int, post_id: int, db_timer: Timer
) -> bool:
    """True se creato, False se già presente (ON CONFLICT)."""
    with db_timer.measure():
        with conn.cursor() as cur:
            cur.execute(_INSERT_LIKE_SQL, {"uid": user_id, "pid": post_id})
            return cur.rowcount > 0


def delete_like(
    conn: Connection, user_id: int, post_id: int, db_timer: Timer
) -> bool:
    """True se cancellato, False se non c'era."""
    with db_timer.measure():
        with conn.cursor() as cur:
            cur.execute(_DELETE_LIKE_SQL, {"uid": user_id, "pid": post_id})
            return cur.rowcount > 0
