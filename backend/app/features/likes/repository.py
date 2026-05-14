"""
Repository per la feature likes.

`ON CONFLICT DO NOTHING` rende l'INSERT idempotente: secondo like dello
stesso utente sullo stesso post non duplica e non solleva eccezioni.
"""

from psycopg2.extensions import connection as Connection


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


def post_exists(conn: Connection, post_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(_POST_EXISTS_SQL, (post_id,))
        return cur.fetchone() is not None


def add_like(conn: Connection, user_id: int, post_id: int) -> bool:
    """True se è stato creato un nuovo like, False se già presente."""
    with conn.cursor() as cur:
        cur.execute(_INSERT_LIKE_SQL, {"uid": user_id, "pid": post_id})
        return cur.rowcount > 0


def remove_like(conn: Connection, user_id: int, post_id: int) -> bool:
    """True se è stata rimossa una riga, False se non c'era."""
    with conn.cursor() as cur:
        cur.execute(_DELETE_LIKE_SQL, {"uid": user_id, "pid": post_id})
        return cur.rowcount > 0
