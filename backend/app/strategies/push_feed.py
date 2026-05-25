"""
Strategy "push_feed".

READ  (timeline): ZRANGE timeline:{viewer} REV 0 limit-1 → se il sorted set
                  non esiste (cold start o TTL scaduto), fallback DB →
                  popola il sorted set con una pipeline → return.
READ  (altri):    identico a cache_aside (lazy loading + TTL).

WRITE on_post_created: fan-out su tutti i follower dell'autore →
                       ZADD timeline:{follower} score=unix_ts member=TimelineItem_json
                       tramite pipeline Redis (un solo round-trip per N follower).
                       Trim automatico a _MAX_TIMELINE per follower per contenere
                       la memoria.

WRITE on_follow_added/removed: DELETE timeline:{follower} → al prossimo
                                fetch_timeline il sorted set si ricostruisce da DB.
                                Nessun backfill: lazy rebuild è sufficiente per
                                i benchmark.

WRITE on_like_added/removed:   aggiorna post:{id} in cache (write-through)
                                — il like_count nelle timeline items è accettabilmente
                                stale (scelta deliberata; aggiornare ogni member del
                                sorted set sarebbe troppo costoso).

Vantaggi  : fetch_timeline è O(log N + limit) su Redis, zero query PG al read.
Svantaggi : on_post_created ha costo O(F) write Redis (F = follower dell'autore).
            Per celebrity con F >> 10^4 il fan-out diventa proibitivo → hybrid.
"""

from __future__ import annotations

from ..cache import Keys
from ..features.feed import repository as feed_repo
from ..features.feed.schemas import FeedItem, TimelineItem
from ..features.posts import repository as posts_repo
from ..features.posts.schemas import Post
from ..features.users import repository as users_repo
from ..features.users.schemas import UserProfile
from .base import CacheStrategy, StrategyContext

# Numero massimo di voci per sorted set timeline. Impedisce crescita illimitata
# della memoria: le voci più vecchie vengono prunate dopo ogni ZADD.
_MAX_TIMELINE = 500

_GET_FOLLOWERS_SQL = "SELECT follower_id FROM follows WHERE followed_id = %(uid)s"


def _tl_key(viewer_id: int) -> str:
    # Chiave separata da Keys.timeline() (che include il limit) perché il
    # sorted set serve richieste con qualsiasi limit ≤ _MAX_TIMELINE.
    return f"timeline:{viewer_id}"


def _get_follower_ids(ctx: StrategyContext, author_id: int) -> list[int]:
    with ctx.db_timer.measure():
        with ctx.conn.cursor() as cur:
            cur.execute(_GET_FOLLOWERS_SQL, {"uid": author_id})
            return [row["follower_id"] for row in cur.fetchall()]


class PushFeedStrategy(CacheStrategy):
    name = "push_feed"

    # --- Reads ---

    def get_user_profile(self, ctx: StrategyContext, user_id: int) -> UserProfile | None:
        key = Keys.user(user_id)
        cached = ctx.cache.get_model(key, UserProfile)
        if cached is not None:
            return cached
        profile = users_repo.query_user_profile(ctx.conn, user_id, ctx.db_timer)
        if profile is not None:
            ctx.cache.set_model(key, profile, ttl=ctx.settings.cache_ttl_user)
        return profile

    def get_post(self, ctx: StrategyContext, post_id: int) -> Post | None:
        key = Keys.post(post_id)
        cached = ctx.cache.get_model(key, Post)
        if cached is not None:
            return cached
        post = posts_repo.query_post(ctx.conn, post_id, ctx.db_timer)
        if post is not None:
            ctx.cache.set_model(key, post, ttl=ctx.settings.cache_ttl_post)
        return post

    def fetch_timeline(
        self, ctx: StrategyContext, viewer_id: int, limit: int
    ) -> list[TimelineItem]:
        key = _tl_key(viewer_id)
        client = ctx.cache._client

        with ctx.cache._timing.cache.measure():
            members = client.zrevrange(key, 0, limit - 1)

        if members:
            ctx.cache._record_hit(True)
            return [TimelineItem.model_validate_json(m) for m in members]

        # Cold start: leggi dal DB e popola il sorted set
        ctx.cache._record_hit(False)
        items = feed_repo.query_timeline(
            ctx.conn,
            viewer_id=viewer_id,
            window_days=ctx.settings.fyp_recency_window_days,
            limit=_MAX_TIMELINE,
            db_timer=ctx.db_timer,
        )
        if items:
            pipe = client.pipeline()
            for item in items:
                pipe.zadd(key, {item.model_dump_json(): item.created_at.timestamp()})
            pipe.expire(key, ctx.settings.cache_ttl_timeline)
            pipe.execute()

        return items[:limit]

    def fetch_fyp(
        self,
        ctx: StrategyContext,
        viewer_id: int,
        limit: int,
        weights: dict[str, float],
    ) -> list[FeedItem]:
        key = Keys.fyp(viewer_id, limit)
        cached = ctx.cache.get_model_list(key, FeedItem)
        if cached is not None:
            return cached
        items = feed_repo.query_fyp(
            ctx.conn,
            viewer_id=viewer_id,
            window_days=ctx.settings.fyp_recency_window_days,
            limit=limit,
            weights=weights,
            db_timer=ctx.db_timer,
        )
        ctx.cache.set_model_list(key, items, ttl=ctx.settings.cache_ttl_feed)
        return items

    def fetch_fyp_with_fof(
        self,
        ctx: StrategyContext,
        viewer_id: int,
        limit: int,
        weights: dict[str, float],
    ) -> list[FeedItem]:
        key = Keys.fyp_fof(viewer_id, limit)
        cached = ctx.cache.get_model_list(key, FeedItem)
        if cached is not None:
            return cached
        items = feed_repo.query_fyp_with_fof(
            ctx.conn,
            viewer_id=viewer_id,
            window_days=ctx.settings.fyp_recency_window_days,
            limit=limit,
            weights=weights,
            db_timer=ctx.db_timer,
        )
        ctx.cache.set_model_list(key, items, ttl=ctx.settings.cache_ttl_feed_fof)
        return items

    # --- Write hooks ---

    def on_post_created(
        self, ctx: StrategyContext, author_id: int, post_id: int
    ) -> None:
        post = posts_repo.query_post(ctx.conn, post_id, ctx.db_timer)
        if post is None:
            return

        ctx.cache.set_model(Keys.post(post_id), post, ttl=ctx.settings.cache_ttl_post)

        profile = users_repo.query_user_profile(ctx.conn, author_id, ctx.db_timer)
        if profile is not None:
            ctx.cache.set_model(Keys.user(author_id), profile, ttl=ctx.settings.cache_ttl_user)

        follower_ids = _get_follower_ids(ctx, author_id)
        if not follower_ids:
            return

        # Costruisce il TimelineItem da aggiungere ai sorted set
        item = TimelineItem(
            post_id=post.post_id,
            user_id=post.user_id,
            content=post.content,
            created_at=post.created_at,
            like_count=post.like_count,
        )
        member = item.model_dump_json()
        score = post.created_at.timestamp()
        ttl = ctx.settings.cache_ttl_timeline
        client = ctx.cache._client

        pipe = client.pipeline()
        for fid in follower_ids:
            tl_key = _tl_key(fid)
            pipe.zadd(tl_key, {member: score})
            # Mantieni solo le _MAX_TIMELINE voci più recenti
            pipe.zremrangebyrank(tl_key, 0, -(_MAX_TIMELINE + 1))
            pipe.expire(tl_key, ttl)
        pipe.execute()

    def on_like_added(
        self, ctx: StrategyContext, user_id: int, post_id: int
    ) -> None:
        post = posts_repo.query_post(ctx.conn, post_id, ctx.db_timer)
        if post is not None:
            ctx.cache.set_model(Keys.post(post_id), post, ttl=ctx.settings.cache_ttl_post)

    def on_like_removed(
        self, ctx: StrategyContext, user_id: int, post_id: int
    ) -> None:
        post = posts_repo.query_post(ctx.conn, post_id, ctx.db_timer)
        if post is not None:
            ctx.cache.set_model(Keys.post(post_id), post, ttl=ctx.settings.cache_ttl_post)

    def on_follow_added(
        self, ctx: StrategyContext, follower_id: int, followed_id: int
    ) -> None:
        # Invalida la timeline del follower: ricostruzione lazy al prossimo fetch
        ctx.cache._client.delete(_tl_key(follower_id))
        for uid in (follower_id, followed_id):
            profile = users_repo.query_user_profile(ctx.conn, uid, ctx.db_timer)
            if profile is not None:
                ctx.cache.set_model(Keys.user(uid), profile, ttl=ctx.settings.cache_ttl_user)

    def on_follow_removed(
        self, ctx: StrategyContext, follower_id: int, followed_id: int
    ) -> None:
        ctx.cache._client.delete(_tl_key(follower_id))
        for uid in (follower_id, followed_id):
            profile = users_repo.query_user_profile(ctx.conn, uid, ctx.db_timer)
            if profile is not None:
                ctx.cache.set_model(Keys.user(uid), profile, ttl=ctx.settings.cache_ttl_user)
