"""
Strategy "cache_aside" (lazy loading).

READ : check Redis → HIT? return. MISS → query PG → set Redis (con TTL) → return.
WRITE: nessuna modifica al flusso DB; gli hook invalidano (DELETE) le chiavi
       impattate. I feed si lasciano scadere per TTL invece di invalidarli
       a ogni POST (eviterebbe fan-out costoso su autori con molti follower).

Mappa chiavi → TTL (configurabili via .env):
  user:{id}                   → CACHE_TTL_USER       (300s)
  post:{id}                   → CACHE_TTL_POST       (300s)
  timeline:{viewer}:{limit}   → CACHE_TTL_TIMELINE   (60s)
  fyp:{viewer}:{limit}        → CACHE_TTL_FEED       (60s)
  fyp_fof:{viewer}:{limit}    → CACHE_TTL_FEED_FOF   (60s)

Invalidazione per evento:
  on_post_created(author)         → DELETE user:{author}      (post_count++)
  on_like_added/removed(_, post)  → DELETE post:{post}        (like_count cambiato)
  on_follow_added/removed(F, D)   → DELETE user:{F}, user:{D} (counter cambiati)

I feed NON vengono invalidati: la finestra di staleness (60s) è una scelta
deliberata di consistency rilassata da motivare nel report.
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


class CacheAsideStrategy(CacheStrategy):
    name = "cache_aside"

    # --- Reads: cache-aside ---

    def get_user_profile(
        self, ctx: StrategyContext, user_id: int
    ) -> UserProfile | None:
        key = Keys.user(user_id)
        cached = ctx.cache.get_model(key, UserProfile)
        if cached is not None:
            return cached
        profile = users_repo.query_user_profile(ctx.read_conn, user_id, ctx.db_timer)
        if profile is not None:
            ctx.cache.set_model(key, profile, ttl=ctx.settings.cache_ttl_user)
        return profile

    def get_post(self, ctx: StrategyContext, post_id: int) -> Post | None:
        key = Keys.post(post_id)
        cached = ctx.cache.get_model(key, Post)
        if cached is not None:
            return cached
        post = posts_repo.query_post(ctx.read_conn, post_id, ctx.db_timer)
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
            ctx.read_conn,
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
            ctx.read_conn,
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
            ctx.read_conn,
            viewer_id=viewer_id,
            window_days=ctx.settings.fyp_recency_window_days,
            limit=limit,
            weights=weights,
            db_timer=ctx.db_timer,
        )
        ctx.cache.set_model_list(key, items, ttl=ctx.settings.cache_ttl_feed_fof)
        return items

    # --- Write hooks: invalidazione event-based ---

    def on_post_created(
        self, ctx: StrategyContext, author_id: int, post_id: int
    ) -> None:
        # post_count del profilo è cambiato → invalida user:{author}
        ctx.cache.delete(Keys.user(author_id))

    def on_like_added(
        self, ctx: StrategyContext, user_id: int, post_id: int
    ) -> None:
        ctx.cache.delete(Keys.post(post_id))

    def on_like_removed(
        self, ctx: StrategyContext, user_id: int, post_id: int
    ) -> None:
        ctx.cache.delete(Keys.post(post_id))

    def on_follow_added(
        self, ctx: StrategyContext, follower_id: int, followed_id: int
    ) -> None:
        # following_count di F e follower_count di D sono cambiati
        ctx.cache.delete(Keys.user(follower_id), Keys.user(followed_id))

    def on_follow_removed(
        self, ctx: StrategyContext, follower_id: int, followed_id: int
    ) -> None:
        ctx.cache.delete(Keys.user(follower_id), Keys.user(followed_id))
