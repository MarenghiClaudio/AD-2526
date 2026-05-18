"""
Repository per la feature users.

Strategia Fase 2 — cache-aside su `user:{id}`:
  READ : check cache → HIT? return. MISS → query PG → set cache (TTL) → return.
  WRITE: la mutazione di un counter (post/follower/following) viene gestita
         dai repository delle feature corrispondenti, che chiamano
         `invalidate(cache, user_id)` qui sotto.

Le funzioni ricevono `db_timer: Timer` esplicito così che il `db_ms`
riportato in `Timing` includa **solo** le chiamate psycopg2 (escludendo
i round-trip a Redis, che sono misurati separatamente in `cache_ms`).
"""

from psycopg2.extensions import connection as Connection

from ...cache import CacheService, Keys
from ...config import get_settings
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


def get_user_profile(
    conn: Connection,
    user_id: int,
    cache: CacheService,
    db_timer: Timer,
) -> UserProfile | None:
    """Profilo utente con counter aggregati (cache-aside)."""
    key = Keys.user(user_id)
    cached = cache.get_model(key, UserProfile)
    if cached is not None:
        return cached

    with db_timer.measure():
        with conn.cursor() as cur:
            cur.execute(_USER_PROFILE_SQL, {"uid": user_id})
            row = cur.fetchone()
    if row is None:
        return None
    profile = UserProfile.model_validate(row)
    cache.set_model(key, profile, ttl=get_settings().cache_ttl_user)
    return profile


def user_exists(conn: Connection, user_id: int, db_timer: Timer) -> bool:
    """
    Check rapido di esistenza utente (per validazione su POST).
    Non passa per la cache: la chiamata è cheap (PK lookup) e si vuole
    sempre vedere lo stato corrente del DB sui guard di scrittura.
    """
    with db_timer.measure():
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
            return cur.fetchone() is not None


def invalidate(cache: CacheService, *user_ids: int) -> None:
    """Cancella le chiavi `user:{id}` (chiamato dai repository di altre feature)."""
    if not user_ids:
        return
    cache.delete(*(Keys.user(uid) for uid in user_ids))
