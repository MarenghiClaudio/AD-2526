"""
Data access per la feature feed.

Tre query SQL distinte (timeline / fyp / fyp_with_fof). Solo SQL: le strategy
decidono se servire da Redis (sorted set push, JSON cache-aside, ...) o
fallback a queste funzioni.
"""

from psycopg2.extensions import connection as Connection

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


def query_timeline(
    conn: Connection,
    *,
    viewer_id: int,
    window_days: int,
    limit: int,
    db_timer: Timer,
) -> list[TimelineItem]:
    """Feed cronologico dal DB (sola SQL, no cache)."""
    with db_timer.measure():
        with conn.cursor() as cur:
            cur.execute(
                _TIMELINE_SQL,
                {"viewer": viewer_id, "window_days": window_days, "limit": limit},
            )
            rows = cur.fetchall()
    return [TimelineItem.model_validate(row) for row in rows]


def query_fyp(
    conn: Connection,
    *,
    viewer_id: int,
    window_days: int,
    limit: int,
    weights: dict[str, float],
    db_timer: Timer,
) -> list[FeedItem]:
    """FYP a 1° grado dal DB (sola SQL)."""
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
    return [FeedItem.model_validate(row) for row in rows]


def query_fyp_with_fof(
    conn: Connection,
    *,
    viewer_id: int,
    window_days: int,
    limit: int,
    weights: dict[str, float],
    db_timer: Timer,
) -> list[FeedItem]:
    """FYP esteso al 2° grado dal DB (sola SQL)."""
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
    return [FeedItem.model_validate(row) for row in rows]
