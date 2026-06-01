"""
Data access per la feature follows.

Solo SQL puro. Le strategy reagiscono via on_follow_added / on_follow_removed.
"""

from psycopg2.extensions import connection as Connection

from ...core.timing import Timer


_INSERT_FOLLOW_SQL = """
INSERT INTO follows (follower_id, followed_id)
VALUES (%(fr)s, %(fd)s)
ON CONFLICT (follower_id, followed_id) DO NOTHING
"""

_DELETE_FOLLOW_SQL = """
DELETE FROM follows
WHERE follower_id = %(fr)s AND followed_id = %(fd)s
"""


def insert_follow(
    conn: Connection, follower_id: int, followed_id: int, db_timer: Timer
) -> bool:
    with db_timer.measure():
        with conn.cursor() as cur:
            cur.execute(_INSERT_FOLLOW_SQL, {"fr": follower_id, "fd": followed_id})
            return cur.rowcount > 0


def delete_follow(
    conn: Connection, follower_id: int, followed_id: int, db_timer: Timer
) -> bool:
    with db_timer.measure():
        with conn.cursor() as cur:
            cur.execute(_DELETE_FOLLOW_SQL, {"fr": follower_id, "fd": followed_id})
            return cur.rowcount > 0
