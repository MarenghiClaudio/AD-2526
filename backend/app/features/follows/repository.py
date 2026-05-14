"""Repository per la feature follows."""

from psycopg2.extensions import connection as Connection


_INSERT_FOLLOW_SQL = """
INSERT INTO follows (follower_id, followed_id)
VALUES (%(fr)s, %(fd)s)
ON CONFLICT (follower_id, followed_id) DO NOTHING
"""

_DELETE_FOLLOW_SQL = """
DELETE FROM follows
WHERE follower_id = %(fr)s AND followed_id = %(fd)s
"""


def add_follow(conn: Connection, follower_id: int, followed_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(_INSERT_FOLLOW_SQL, {"fr": follower_id, "fd": followed_id})
        return cur.rowcount > 0


def remove_follow(conn: Connection, follower_id: int, followed_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(_DELETE_FOLLOW_SQL, {"fr": follower_id, "fd": followed_id})
        return cur.rowcount > 0
