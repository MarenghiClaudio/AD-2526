"""Repository per la feature posts."""

from psycopg2.extensions import connection as Connection

from .schemas import CreatePostResponse, Post


_GET_POST_SQL = """
SELECT
    p.post_id,
    p.user_id,
    p.content,
    p.created_at,
    COALESCE(l.cnt, 0) AS like_count
FROM posts p
LEFT JOIN (
    SELECT post_id, COUNT(*) AS cnt FROM likes WHERE post_id = %(pid)s GROUP BY post_id
) l ON l.post_id = p.post_id
WHERE p.post_id = %(pid)s
"""


_INSERT_POST_SQL = """
INSERT INTO posts (user_id, content)
VALUES (%(uid)s, %(content)s)
RETURNING post_id, user_id, content, created_at
"""


def get_post(conn: Connection, post_id: int) -> Post | None:
    """Singolo post con like_count aggregato. None se non esiste."""
    with conn.cursor() as cur:
        cur.execute(_GET_POST_SQL, {"pid": post_id})
        row = cur.fetchone()
    if row is None:
        return None
    return Post.model_validate(row)


def create_post(conn: Connection, user_id: int, content: str) -> CreatePostResponse:
    """Inserisce un post e ritorna i metadati assegnati dal DB."""
    with conn.cursor() as cur:
        cur.execute(_INSERT_POST_SQL, {"uid": user_id, "content": content})
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("INSERT ... RETURNING did not return a row")
    return CreatePostResponse.model_validate(row)
