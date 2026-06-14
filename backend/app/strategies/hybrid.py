"""
Strategy "hybrid".

Obiettivo:
  - User/post/FYP/FYP_FOF: cache-aside classico.
  - Timeline: chiave deterministica `timeline:{viewer_id}` (senza limit),
    invalidazione bulk per follower non-celebrity.
  - Celebrity (follower_count > threshold): niente fan-out; timeline
    scade via TTL.

Rispetto alla versione precedente il fix principale è in
_delete_timelines_for_viewers: invece di chiamare scan_delete per ogni
follower (O(N) SCAN × numero_follower), si raccolgono tutte le chiavi
e si fa un unico delete(*keys) — identico all'approccio di push_feed.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterable

from ..cache import Keys
from ..features.feed import repository as feed_repo
from ..features.feed.schemas import FeedItem, TimelineItem
from ..features.posts import repository as posts_repo
from ..features.posts.schemas import Post
from ..features.users import repository as users_repo
from ..features.users.schemas import UserProfile
from .base import CacheStrategy, StrategyContext

logger = logging.getLogger(__name__)


def _tl_key(viewer_id: int) -> str:
    """Chiave timeline senza limit — deterministica, cancellabile senza SCAN."""
    return f"timeline:{viewer_id}"


class HybridStrategy(CacheStrategy):
    name = "hybrid"

    def _celebrity_threshold(self, ctx: StrategyContext) -> int:
        return int(
            getattr(
                ctx.settings,
                "hybrid_celebrity_threshold",
                os.getenv("HYBRID_CELEBRITY_THRESHOLD", "1000"),
            )
        )

    def _query_follower_ids_limited(
        self, ctx: StrategyContext, user_id: int, limit: int
    ) -> list[int]:
        """
        Ritorna al massimo `limit` follower ID.
        Se vengono ritornate threshold+1 righe, l'autore è celebrity.
        """
        with ctx.db_timer.measure():
            with ctx.conn.cursor() as cur:
                cur.execute(
                    "SELECT follower_id FROM follows WHERE followed_id = %s LIMIT %s",
                    (user_id, limit),
                )
                return [row["follower_id"] for row in cur.fetchall()]

    def _delete_timelines_for_viewers(
        self, ctx: StrategyContext, viewer_ids: Iterable[int]
    ) -> None:
        """
        Invalida le chiavi timeline di tutti i viewer in un unico delete bulk,
        senza SCAN. Identico all'approccio di push_feed.
        """
        keys = [_tl_key(vid) for vid in viewer_ids]
        if not keys:
            return
        try:
            ctx.cache.delete(*keys)
        except Exception:
            pass

    # --- Reads: cache-aside ---

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
        key = _tl_key(viewer_id)
        cached = ctx.cache.get_model_list(key, TimelineItem)
        if cached is not None:
            return cached[:limit]
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

    # --- Write hooks ---

    def on_post_created(
        self, ctx: StrategyContext, author_id: int, post_id: int
    ) -> None:
        t0 = time.monotonic()

        self._safe_delete(ctx, Keys.user(author_id))
        t1 = time.monotonic()

        try:
            post = posts_repo.query_post(ctx.conn, post_id, ctx.db_timer)
            if post is not None:
                ctx.cache.set_model(
                    Keys.post(post_id), post, ttl=ctx.settings.cache_ttl_post
                )
        except Exception:
            pass
        t2 = time.monotonic()

        try:
            threshold = self._celebrity_threshold(ctx)
            follower_ids = self._query_follower_ids_limited(
                ctx, author_id, limit=threshold + 1
            )
            t3 = time.monotonic()
            n = len(follower_ids)
            if n > threshold:
                logger.warning(
                    "hybrid.on_post_created celebrity user=%d | "
                    "del_user=%.1f ms | query_post=%.1f ms | "
                    "query_followers=%.1f ms (%d rows) | total=%.1f ms",
                    author_id,
                    (t1 - t0) * 1000,
                    (t2 - t1) * 1000,
                    (t3 - t2) * 1000,
                    n,
                    (t3 - t0) * 1000,
                )
                return
            self._delete_timelines_for_viewers(ctx, follower_ids)
            t4 = time.monotonic()
            logger.warning(
                "hybrid.on_post_created user=%d | "
                "del_user=%.1f ms | query_post=%.1f ms | "
                "query_followers=%.1f ms (%d rows) | del_timelines=%.1f ms | total=%.1f ms",
                author_id,
                (t1 - t0) * 1000,
                (t2 - t1) * 1000,
                (t3 - t2) * 1000,
                n,
                (t4 - t3) * 1000,
                (t4 - t0) * 1000,
            )
        except Exception:
            return

    def _safe_delete(self, ctx: StrategyContext, *keys: str) -> None:
        if not keys:
            return
        try:
            ctx.cache.delete(*keys)
        except Exception:
            pass

    def on_like_added(
        self, ctx: StrategyContext, user_id: int, post_id: int
    ) -> None:
        self._safe_delete(ctx, Keys.post(post_id))

    def on_like_removed(
        self, ctx: StrategyContext, user_id: int, post_id: int
    ) -> None:
        self._safe_delete(ctx, Keys.post(post_id))

    def on_follow_added(
        self, ctx: StrategyContext, follower_id: int, followed_id: int
    ) -> None:
        self._safe_delete(ctx, Keys.user(follower_id), Keys.user(followed_id))
        self._delete_timelines_for_viewers(ctx, [follower_id])

    def on_follow_removed(
        self, ctx: StrategyContext, follower_id: int, followed_id: int
    ) -> None:
        self._safe_delete(ctx, Keys.user(follower_id), Keys.user(followed_id))
        self._delete_timelines_for_viewers(ctx, [follower_id])
