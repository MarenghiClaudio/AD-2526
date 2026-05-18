"""
Repository per la feature posts.

Strategia Fase 2 — cache-aside su `post:{id}`:
  READ : check cache → HIT? return. MISS → query PG → set cache → return.
  WRITE (create_post): invalida `user:{author_id}` perché il counter
                        post_count del profilo è cambiato. Il post nuovo
                        non viene popolato pro-attivamente in cache:
                        verrà cachato al primo GET (lazy population).
"""

from psycopg2.extensions import connection as Connection

from ...cache import CacheService, Keys
from ...config import get_settings
from ...core.timing import Timer
from ..users import repository as users_repo
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


def get_post(
    conn: Connection,
    post_id: int,
    cache: CacheService,
    db_timer: Timer,
) -> Post | None:
    """Singolo post con like_count aggregato (cache-aside)."""
    key = Keys.post(post_id)
    cached = cache.get_model(key, Post)
    if cached is not None:
        return cached

    with db_timer.measure():
        with conn.cursor() as cur:
            cur.execute(_GET_POST_SQL, {"pid": post_id})
            row = cur.fetchone()
    if row is None:
        return None
    post = Post.model_validate(row)
    cache.set_model(key, post, ttl=get_settings().cache_ttl_post)
    return post


def create_post(
    conn: Connection,
    user_id: int,
    content: str,
    cache: CacheService,
    db_timer: Timer,
) -> CreatePostResponse:
    """Inserisce un post e invalida il profilo dell'autore (post_count++)."""
    with db_timer.measure():
        with conn.cursor() as cur:
            cur.execute(_INSERT_POST_SQL, {"uid": user_id, "content": content})
            row = cur.fetchone()
    if row is None:
        raise RuntimeError("INSERT ... RETURNING did not return a row")
    users_repo.invalidate(cache, user_id)
    return CreatePostResponse.model_validate(row)


def invalidate(cache: CacheService, *post_ids: int) -> None:
    """Cancella le chiavi `post:{id}` (chiamato da likes repo dopo mutazione)."""
    if not post_ids:
        return
    cache.delete(*(Keys.post(pid) for pid in post_ids))
