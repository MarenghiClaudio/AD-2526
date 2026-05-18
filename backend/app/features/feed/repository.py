"""
Repository per la feature feed.

Tre query distinte, ognuna pensata per uno scenario di benchmark:

  1. `fetch_timeline`    — feed cronologico semplice (baseline).
      WHERE user_id IN (chi seguo) ORDER BY created_at DESC LIMIT N
      È il caso d'uso che PostgreSQL gestisce bene con l'indice composito
      idx_posts_user_created. Sarà la baseline più "facile" da battere
      via cache (sorted set Redis con la timeline pre-calcolata).

  2. `fetch_fyp`         — FYP a 1° grado (solo follow diretti).
      Calcola lo score in SQL combinando recency / affinity / popularity.
      Più costoso per via di EXP/LN su molti post candidati.

  3. `fetch_fyp_with_fof` — FYP esteso al 2° grado (follower-of-follower).
      Espande l'insieme dei candidati a due livelli di follow. È la query
      "spettacolare" per il caching: per power-user con migliaia di follow
      diretti, l'insieme FoF può contenere milioni di candidati ed è il
      caso in cui Redis darà i guadagni più visibili.

Il calcolo del punteggio è espresso direttamente in SQL così che il piano
di esecuzione di Postgres sia onesto (no Python-side ranking, no
materializzazione preliminare in memoria del client).
"""

from psycopg2.extensions import connection as Connection

from ...cache import CacheService, Keys
from ...config import get_settings
from ...core.timing import Timer
from .schemas import FeedItem, TimelineItem


_TIMELINE_SQL = """
WITH followed AS (
    SELECT followed_id FROM follows WHERE follower_id = %(viewer)s
)
SELECT
    p.post_id,
    p.user_id,
    p.content,
    p.created_at,
    COALESCE(l.cnt, 0) AS like_count
FROM posts p
JOIN followed f ON f.followed_id = p.user_id
LEFT JOIN (
    SELECT post_id, COUNT(*) AS cnt FROM likes GROUP BY post_id
) l ON l.post_id = p.post_id
WHERE p.created_at >= NOW() - (%(window_days)s || ' days')::interval
ORDER BY p.created_at DESC
LIMIT %(limit)s
"""


# FYP senza FoF: candidati = post di chi seguo, score combinato in SQL.
_FYP_SQL = """
WITH followed AS (
    SELECT followed_id FROM follows WHERE follower_id = %(viewer)s
),
candidates AS (
    SELECT
        p.post_id,
        p.user_id,
        p.content,
        p.created_at,
        %(affinity_direct)s::float AS affinity
    FROM posts p
    JOIN followed f ON f.followed_id = p.user_id
    WHERE p.created_at >= NOW() - (%(window_days)s || ' days')::interval
),
candidates_likes AS (
    SELECT c.*, COALESCE(l.cnt, 0) AS like_count
    FROM candidates c
    LEFT JOIN (
        SELECT post_id, COUNT(*) AS cnt FROM likes GROUP BY post_id
    ) l ON l.post_id = c.post_id
)
SELECT
    post_id,
    user_id,
    content,
    created_at,
    like_count,
    affinity,
    (
        %(w_recency)s * EXP(- EXTRACT(EPOCH FROM (NOW() - created_at)) / %(tau_sec)s)
      + %(w_affinity)s * affinity
      + %(w_popularity)s * LN(1 + like_count)
    ) AS score
FROM candidates_likes
ORDER BY score DESC
LIMIT %(limit)s
"""


# FYP con FoF: due insiemi di candidati uniti con affinity differenziata.
# - Direct follows  → affinity = fyp_affinity_direct
# - Follower-of-follower → affinity = fyp_affinity_fof
# Si esclude esplicitamente il viewer e si scartano gli utenti già
# presenti nei direct follows per non doppiare l'affinity.
_FYP_FOF_SQL = """
WITH direct_follows AS (
    SELECT followed_id FROM follows WHERE follower_id = %(viewer)s
),
fof AS (
    SELECT DISTINCT f2.followed_id AS fof_id
    FROM follows f1
    JOIN follows f2 ON f2.follower_id = f1.followed_id
    WHERE f1.follower_id = %(viewer)s
      AND f2.followed_id <> %(viewer)s
      AND f2.followed_id NOT IN (SELECT followed_id FROM direct_follows)
),
candidates AS (
    SELECT
        p.post_id, p.user_id, p.content, p.created_at,
        %(affinity_direct)s::float AS affinity
    FROM posts p
    JOIN direct_follows df ON df.followed_id = p.user_id
    WHERE p.created_at >= NOW() - (%(window_days)s || ' days')::interval

    UNION ALL

    SELECT
        p.post_id, p.user_id, p.content, p.created_at,
        %(affinity_fof)s::float AS affinity
    FROM posts p
    JOIN fof ON fof.fof_id = p.user_id
    WHERE p.created_at >= NOW() - (%(window_days)s || ' days')::interval
),
candidates_likes AS (
    SELECT c.*, COALESCE(l.cnt, 0) AS like_count
    FROM candidates c
    LEFT JOIN (
        SELECT post_id, COUNT(*) AS cnt FROM likes GROUP BY post_id
    ) l ON l.post_id = c.post_id
)
SELECT
    post_id,
    user_id,
    content,
    created_at,
    like_count,
    affinity,
    (
        %(w_recency)s * EXP(- EXTRACT(EPOCH FROM (NOW() - created_at)) / %(tau_sec)s)
      + %(w_affinity)s * affinity
      + %(w_popularity)s * LN(1 + like_count)
    ) AS score
FROM candidates_likes
ORDER BY score DESC
LIMIT %(limit)s
"""


def fetch_timeline(
    conn: Connection,
    *,
    viewer_id: int,
    window_days: int,
    limit: int,
    cache: CacheService,
    db_timer: Timer,
) -> list[TimelineItem]:
    """Feed cronologico (cache-aside): solo i post degli utenti seguiti."""
    key = Keys.timeline(viewer_id, limit)
    cached = cache.get_model_list(key, TimelineItem)
    if cached is not None:
        return cached

    with db_timer.measure():
        with conn.cursor() as cur:
            cur.execute(
                _TIMELINE_SQL,
                {"viewer": viewer_id, "window_days": window_days, "limit": limit},
            )
            rows = cur.fetchall()
    items = [TimelineItem.model_validate(row) for row in rows]
    cache.set_model_list(key, items, ttl=get_settings().cache_ttl_timeline)
    return items


def fetch_fyp(
    conn: Connection,
    *,
    viewer_id: int,
    window_days: int,
    limit: int,
    weights: dict[str, float],
    cache: CacheService,
    db_timer: Timer,
) -> list[FeedItem]:
    """FYP a 1° grado (cache-aside)."""
    key = Keys.fyp(viewer_id, limit)
    cached = cache.get_model_list(key, FeedItem)
    if cached is not None:
        return cached

    params = {
        "viewer": viewer_id,
        "window_days": window_days,
        "limit": limit,
        **weights,
    }
    with db_timer.measure():
        with conn.cursor() as cur:
            cur.execute(_FYP_SQL, params)
            rows = cur.fetchall()
    items = [FeedItem.model_validate(row) for row in rows]
    cache.set_model_list(key, items, ttl=get_settings().cache_ttl_feed)
    return items


def fetch_fyp_with_fof(
    conn: Connection,
    *,
    viewer_id: int,
    window_days: int,
    limit: int,
    weights: dict[str, float],
    cache: CacheService,
    db_timer: Timer,
) -> list[FeedItem]:
    """FYP esteso al 2° grado (cache-aside)."""
    key = Keys.fyp_fof(viewer_id, limit)
    cached = cache.get_model_list(key, FeedItem)
    if cached is not None:
        return cached

    params = {
        "viewer": viewer_id,
        "window_days": window_days,
        "limit": limit,
        **weights,
    }
    with db_timer.measure():
        with conn.cursor() as cur:
            cur.execute(_FYP_FOF_SQL, params)
            rows = cur.fetchall()
    items = [FeedItem.model_validate(row) for row in rows]
    cache.set_model_list(key, items, ttl=get_settings().cache_ttl_feed_fof)
    return items
