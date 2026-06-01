"""
Strategy "no_cache": bypassa completamente Redis.

Tutte le letture vanno a PostgreSQL. Tutti gli hook di scrittura sono no-op.
Equivalente alla baseline di Fase 1: utile per A/B testing contro le altre
strategy senza dover smontare l'infrastruttura.

Per attivarla:
    .env  →  CACHE_STRATEGY=no_cache
"""

from __future__ import annotations

from ..features.feed import repository as feed_repo
from ..features.feed.schemas import FeedItem, TimelineItem
from ..features.posts import repository as posts_repo
from ..features.posts.schemas import Post
from ..features.users import repository as users_repo
from ..features.users.schemas import UserProfile
from .base import CacheStrategy, StrategyContext


class NoCacheStrategy(CacheStrategy):
    name = "no_cache"

    # --- Reads → sempre DB ---

    def get_user_profile(
        self, ctx: StrategyContext, user_id: int
    ) -> UserProfile | None:
        return users_repo.query_user_profile(ctx.conn, user_id, ctx.db_timer)

    def get_post(self, ctx: StrategyContext, post_id: int) -> Post | None:
        return posts_repo.query_post(ctx.conn, post_id, ctx.db_timer)

    def fetch_timeline(
        self, ctx: StrategyContext, viewer_id: int, limit: int
    ) -> list[TimelineItem]:
        return feed_repo.query_timeline(
            ctx.conn,
            viewer_id=viewer_id,
            window_days=ctx.settings.fyp_recency_window_days,
            limit=limit,
            db_timer=ctx.db_timer,
        )

    def fetch_fyp(
        self,
        ctx: StrategyContext,
        viewer_id: int,
        limit: int,
        weights: dict[str, float],
    ) -> list[FeedItem]:
        return feed_repo.query_fyp(
            ctx.conn,
            viewer_id=viewer_id,
            window_days=ctx.settings.fyp_recency_window_days,
            limit=limit,
            weights=weights,
            db_timer=ctx.db_timer,
        )

    def fetch_fyp_with_fof(
        self,
        ctx: StrategyContext,
        viewer_id: int,
        limit: int,
        weights: dict[str, float],
    ) -> list[FeedItem]:
        return feed_repo.query_fyp_with_fof(
            ctx.conn,
            viewer_id=viewer_id,
            window_days=ctx.settings.fyp_recency_window_days,
            limit=limit,
            weights=weights,
            db_timer=ctx.db_timer,
        )

    # --- Write hooks → no-op (niente cache da aggiornare) ---

    def on_post_created(
        self, ctx: StrategyContext, author_id: int, post_id: int
    ) -> None:
        return None

    def on_like_added(
        self, ctx: StrategyContext, user_id: int, post_id: int
    ) -> None:
        return None

    def on_like_removed(
        self, ctx: StrategyContext, user_id: int, post_id: int
    ) -> None:
        return None

    def on_follow_added(
        self, ctx: StrategyContext, follower_id: int, followed_id: int
    ) -> None:
        return None

    def on_follow_removed(
        self, ctx: StrategyContext, follower_id: int, followed_id: int
    ) -> None:
        return None
