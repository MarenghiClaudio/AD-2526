"""
Strategy "hybrid" - versione piu robusta.

Obiettivo:
  - User/post/FYP/FYP_FOF: cache-aside classico.
  - Timeline: invalidazione mirata per utenti non-celebrity.
  - Celebrity: niente fan-out; timeline lasciate scadere via TTL.

"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence

from ..cache import Keys
from ..features.feed import repository as feed_repo
from ..features.feed.schemas import FeedItem, TimelineItem
from ..features.posts import repository as posts_repo
from ..features.posts.schemas import Post
from ..features.users import repository as users_repo
from ..features.users.schemas import UserProfile
from .base import CacheStrategy, StrategyContext


class HybridStrategy(CacheStrategy):
    name = "hybrid"

    # --- Config helpers ---

    def _celebrity_threshold(self, ctx: StrategyContext) -> int:
        return int(
            getattr(
                ctx.settings,
                "hybrid_celebrity_threshold",
                os.getenv("HYBRID_CELEBRITY_THRESHOLD", "1000"),
            )
        )

    def _push_limits(self, ctx: StrategyContext) -> tuple[int, ...]:
        raw = getattr(
            ctx.settings,
            "hybrid_push_timeline_limits",
            os.getenv("HYBRID_PUSH_TIMELINE_LIMITS", "20,50"),
        )
        if isinstance(raw, str):
            limits = [int(x.strip()) for x in raw.split(",") if x.strip()]
        elif isinstance(raw, Iterable):
            limits = [int(x) for x in raw]
        else:
            limits = [int(raw)]
        return tuple(sorted({limit for limit in limits if limit > 0}))

    # --- Small utilities ---

    @staticmethod
    def _chunks(values: Sequence[str], size: int = 250) -> Iterable[Sequence[str]]:
        for start in range(0, len(values), size):
            yield values[start : start + size]

    @staticmethod
    def _row_value(row: object, key: str, index: int = 0) -> object:
        """Read a DB row value from either dict-like or tuple-like cursors."""
        if isinstance(row, Mapping):
            return row[key]
        return row[index]  # type: ignore[index]

    def _safe_delete(self, ctx: StrategyContext, *keys: str) -> None:
        """Best-effort Redis invalidation: cache failures must not break writes."""
        if not keys:
            return
        for chunk in self._chunks(list(keys)):
            try:
                ctx.cache.delete(*chunk)
            except Exception:
                # Caching is an optimization. The DB write has already committed;
                # stale keys will expire by TTL if invalidation fails.
                return

    # --- DB helpers ---

    def _query_follower_ids_limited(
        self, ctx: StrategyContext, user_id: int, limit: int
    ) -> list[int]:
        """
        Return at most `limit` follower IDs.

        The caller requests threshold + 1 rows: if more than threshold rows are
        returned, the author is treated as celebrity and we avoid fan-out.
        """
        with ctx.conn.cursor() as cur:
            cur.execute(
                """
                SELECT follower_id
                FROM follows
                WHERE followed_id = %s
                LIMIT %s
                """,
                (user_id, limit),
            )
            return [
                int(self._row_value(row, "follower_id"))
                for row in cur.fetchall()
            ]

    def _delete_timelines_for_limits(
        self,
        ctx: StrategyContext,
        viewer_ids: Iterable[int],
        limits: tuple[int, ...] | None = None,
    ) -> None:
        selected_limits = limits if limits is not None else self._push_limits(ctx)
        keys = [
            Keys.timeline(viewer_id, limit)
            for viewer_id in viewer_ids
            for limit in selected_limits
        ]
        self._safe_delete(ctx, *keys)

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

    # --- Write hooks ---

    def on_post_created(
        self, ctx: StrategyContext, author_id: int, post_id: int
    ) -> None:
        # post_count del profilo autore cambia sempre.
        self._safe_delete(ctx, Keys.user(author_id))

        # Warm del post appena creato. Se fallisce, non deve rompere la write.
        try:
            post = posts_repo.query_post(ctx.conn, post_id, ctx.db_timer)
            if post is not None:
                ctx.cache.set_model(
                    Keys.post(post_id), post, ttl=ctx.settings.cache_ttl_post
                )
        except Exception:
            pass

        # Invalidazione timeline follower: best effort.
        # Qualsiasi problema qui non deve trasformare POST /posts in 500.
        try:
            threshold = self._celebrity_threshold(ctx)
            limits = self._push_limits(ctx)
            follower_ids = self._query_follower_ids_limited(
                ctx, author_id, limit=threshold + 1
            )

            # Celebrity: threshold + 1 righe trovate => niente fan-out.
            if len(follower_ids) > threshold:
                return

            self._delete_timelines_for_limits(ctx, follower_ids, limits)
        except Exception:
            # Feed/timeline resteranno eventualmente stale fino al TTL.
            return

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
        self._delete_timelines_for_limits(ctx, [follower_id])

    def on_follow_removed(
        self, ctx: StrategyContext, follower_id: int, followed_id: int
    ) -> None:
        self._safe_delete(ctx, Keys.user(follower_id), Keys.user(followed_id))
        self._delete_timelines_for_limits(ctx, [follower_id])
