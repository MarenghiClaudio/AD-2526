"""
Strategy "write_through".

READ : identica a cache_aside — check Redis → HIT? return. MISS → query PG →
       set Redis (con TTL) → return.

WRITE: dopo che PG ha confermato la mutazione, aggiorna *proattivamente* la cache
       con i dati freschi appena letti dal DB, invece di limitarsi a invalidare
       la chiave. Il prossimo lettore troverà un HIT garantito.

       Differenza rispetto a cache_aside:
         cache_aside  →  DELETE key  (next read è MISS → cold hit)
         write_through → SET key     (next read è HIT  → zero cold miss)

       Il vantaggio si vede su workload ad alta coerenza o read-after-write.
       Il costo è che ogni scrittura porta con sé una query DB extra per rileggere
       lo stato aggiornato e due round-trip Redis (SET invece di DEL).

Mappa chiavi/TTL (invariata rispetto a cache_aside):
  user:{id}   → CACHE_TTL_USER  (300s)   ← aggiornato su post_created, follow_*
  post:{id}   → CACHE_TTL_POST  (300s)   ← aggiornato su post_created, like_*
  timeline/fyp/fyp_fof → lasciate scadere per TTL (fan-out costoso, scelta deliberata)
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


class WriteThroughStrategy(CacheStrategy):
    name = "write_through"

    # --- Reads: cache-aside (lazy population) ---

    def get_user_profile(
        self, ctx: StrategyContext, user_id: int
    ) -> UserProfile | None:
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
        key = Keys.timeline(viewer_id, limit)
        cached = ctx.cache.get_model_list(key, TimelineItem)
        if cached is not None:
            return cached
        items = feed_repo.query_timeline(
            ctx.conn,
            viewer_id=viewer_id,
            window_days=ctx.settings.fyp_recency_window_days,
            limit=limit,
            db_timer=ctx.db_timer,
        )
        ctx.cache.set_model_list(key, items, ttl=ctx.settings.cache_ttl_timeline)
        return items

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

    # --- Write hooks: aggiornamento proattivo (write-through) ---

    def on_post_created(
        self, ctx: StrategyContext, author_id: int, post_id: int
    ) -> None:
        # Scrivi il nuovo post in cache (già in PG, lo leggiamo freschi)
        post = posts_repo.query_post(ctx.conn, post_id, ctx.db_timer)
        if post is not None:
            ctx.cache.set_model(Keys.post(post_id), post, ttl=ctx.settings.cache_ttl_post)

        # Aggiorna il profilo dell'autore (post_count è appena incrementato)
        profile = users_repo.query_user_profile(ctx.conn, author_id, ctx.db_timer)
        if profile is not None:
            ctx.cache.set_model(Keys.user(author_id), profile, ttl=ctx.settings.cache_ttl_user)

    def on_like_added(
        self, ctx: StrategyContext, user_id: int, post_id: int
    ) -> None:
        # like_count del post è cambiato → rileggi e aggiorna la cache
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
        # following_count di follower e follower_count di followed sono cambiati
        for uid in (follower_id, followed_id):
            profile = users_repo.query_user_profile(ctx.conn, uid, ctx.db_timer)
            if profile is not None:
                ctx.cache.set_model(Keys.user(uid), profile, ttl=ctx.settings.cache_ttl_user)

    def on_follow_removed(
        self, ctx: StrategyContext, follower_id: int, followed_id: int
    ) -> None:
        for uid in (follower_id, followed_id):
            profile = users_repo.query_user_profile(ctx.conn, uid, ctx.db_timer)
            if profile is not None:
                ctx.cache.set_model(Keys.user(uid), profile, ttl=ctx.settings.cache_ttl_user)
