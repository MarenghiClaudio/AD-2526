"""
Repository per la feature users.

Tutta la logica di accesso al DB sta qui. In Fase 2 questo modulo diventa
il punto naturale dove inserire la cache (lookup Redis prima del PG, write
back dopo). Le funzioni accettano la connessione come parametro — niente
side effect su stato globale.
"""
import json

from psycopg2.extensions import connection as Connection

from .schemas import UserProfile
from app.cache import get_redis, is_cache_enabled
from app.config import get_settings


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


def get_user_profile(conn: Connection, user_id: int) -> UserProfile | None:
    """Profilo utente con counter aggregati. None se l'utente non esiste."""
    if is_cache_enabled():
        cache_key = f"user:{user_id}:profile"
        r = get_redis()
        cached = r.get(cache_key)
        if cached:
            return UserProfile.model_validate(json.loads(cached))

    with conn.cursor() as cur:
        cur.execute(_USER_PROFILE_SQL, {"uid": user_id})
        row = cur.fetchone()
    if row is None:
        return None

    profile = UserProfile.model_validate(row)
    if is_cache_enabled():
        r.setex(cache_key, get_settings().redis_ttl_user_profile, profile.model_dump_json())
    return profile


def user_exists(conn: Connection, user_id: int) -> bool:
    """Check rapido di esistenza utente (per validazione su POST)."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
        return cur.fetchone() is not None

def invalidate_user_profile(user_id: int) -> None:
    """Chiamare dopo ogni write che altera i contatori (like, follow, post)."""
    if is_cache_enabled():
        get_redis().delete(f"user:{user_id}:profile")