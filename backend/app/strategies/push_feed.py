"""
Strategy "push_feed" (v2).

DESIGN AGGIORNATO (rispetto alla v1)
-----------------------------------
v1 memorizzava nel sorted set di ogni follower il JSON completo del
TimelineItem. Due problemi:
  1. Esplosione di memoria Redis: un post in N timeline = N copie del JSON.
  2. Incoerenza del like_count: aggiornare il Post non aggiornava le
     copie embedded, e mantenere coerenza richiederebbe ZADD su ogni
     timeline impattata ad ogni like (proibitivo).

v2 memorizza nel sorted set SOLO il `post_id` (score = unix timestamp del
created_at). Al read time:
  ZREVRANGE timeline:{viewer} 0 limit-1   →  lista di post_id
  MGET post:{id1} post:{id2} ...          →  Post fresco dalla cache
  loop di query_post per i post_id non in cache (miss/evicted)

Vantaggi rispetto a v1:
  - memoria Redis O(numero_post) invece di O(numero_post × follower_medio)
  - like_count sempre coerente (la fonte è sempre `post:{id}`)
  - le mutazioni di like (`on_like_*`) restano locali alla chiave `post:{id}`

Trade-off:
  - read di timeline ha 1 round-trip extra (MGET) rispetto al ZRANGE solo
  - se i `post:{id}` sono scaduti o evicted, serve fallback PG: 1 query
    `query_post` per ogni miss (vedi nota in `fetch_timeline`)

OPERAZIONI
----------
READ  (timeline):  ZREVRANGE timeline:{viewer} → MGET post:{id} →
                   loop query_post sui miss.
READ  (altri):     cache-aside (lazy loading + TTL), identico a cache_aside.

WRITE on_post_created:  write-through su `post:{id}`, aggiorna profilo
                        autore, poi fan-out di post_id su tutti i follower.
                        Il fan-out usa `cache.zadd_fanout(...)` che esegue
                        ZREMRANGEBYRANK solo quando la cardinalità del
                        sorted set supera _MAX_TIMELINE.

WRITE on_follow_*:      invalida timeline:{follower} (rebuild lazy al
                        prossimo fetch) + rilegge entrambi i profili
                        (2 query PG sequenziali, come oggi).

WRITE on_like_*:        write-through su `post:{id}`. Le timeline non
                        vanno toccate: contengono solo id e il MGET al
                        prossimo read legge il like_count fresco.

DIPENDENZE NUOVE SU CacheService (vedi `_cache_service_patch.py`)
  - zrevrange_ids   (read ZSET)
  - zadd_bulk       (rebuild ZSET)
  - zadd_fanout     (fan-out write con trim condizionale)
  - mget_models     (MGET batch)
  - delete_keys     (alias semantico di delete per ZSET)

DIPENDENZE SUI REPOSITORY: nessuna nuova. Usa solo le funzioni esistenti
(query_post, query_user_profile, query_timeline).
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

# Numero massimo di voci per sorted set timeline. Limita la memoria Redis.
# Il trim viene eseguito SOLO se la cardinalità del set eccede questa
# soglia dopo lo ZADD (vedi CacheService.zadd_fanout).
_MAX_TIMELINE = 500

_GET_FOLLOWERS_SQL = "SELECT follower_id FROM follows WHERE followed_id = %(uid)s"


def _tl_key(viewer_id: int) -> str:
    """
    Chiave del sorted set timeline. Separata da `Keys.timeline(viewer, limit)`
    perché lo ZSET non dipende dal limit: serve qualsiasi richiesta con
    limit ≤ _MAX_TIMELINE.
    """
    return f"timeline:{viewer_id}"


def _get_follower_ids(ctx: StrategyContext, author_id: int) -> list[int]:
    """
    Ritorna gli id dei follower di `author_id`.

    Il pool in `app/db.py` è configurato con `RealDictCursor` come default,
    quindi `row["follower_id"]` funziona senza factory esplicito.
    """
    with ctx.db_timer.measure():
        with ctx.conn.cursor() as cur:
            cur.execute(_GET_FOLLOWERS_SQL, {"uid": author_id})
            return [row["follower_id"] for row in cur.fetchall()]


class PushFeedStrategy(CacheStrategy):
    name = "push_feed"

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

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
        """
        Read path "ZSET di id + MGET dei dettagli":
          1. ZREVRANGE timeline:{viewer}     → lista di post_id ordinata
          2. MGET post:{id1}, post:{id2}, …  → Post freschi dalla cache
          3. Per i miss: loop di query_post, ripopola `post:{id}`
          4. Proietta Post → TimelineItem mantenendo l'ordine dello ZSET

        NB sui MISS: `query_post` per ogni id mancante è una scelta
        deliberata (semplicità sopra throughput). In regime di cache calda
        i miss sono rari (post evicted da Redis durante alta pressione di
        memoria, o tornati validi dopo TTL scaduto). Se i miss diventassero
        frequenti, introdurre `query_posts_by_ids` batch nel repository.
        """
        tl_key = _tl_key(viewer_id)

        # Step 1: leggi gli id dal sorted set.
        # zrevrange_ids distingue tra "ZSET inesistente" (None → rebuild)
        # e "ZSET esistente ma vuoto" ([] → utente senza follow attivi).
        post_ids = ctx.cache.zrevrange_ids(tl_key, end=limit - 1)

        if post_ids is None:
            return self._rebuild_timeline(ctx, viewer_id, limit)

        if not post_ids:
            return []

        # Step 2: MGET batch dei Post.
        post_keys = [Keys.post(pid) for pid in post_ids]
        posts = ctx.cache.mget_models(post_keys, Post)

        # Step 3: fallback PG per i post miss/scaduti dalla cache.
        # Loop di query_post: 1 query per ogni miss. In regime di cache
        # calda i miss sono rari e questo loop è quasi mai eseguito.
        for i, p in enumerate(posts):
            if p is not None:
                continue
            pid = post_ids[i]
            fresh = posts_repo.query_post(ctx.read_conn, pid, ctx.db_timer)
            if fresh is not None:
                ctx.cache.set_model(
                    Keys.post(pid), fresh, ttl=ctx.settings.cache_ttl_post
                )
            posts[i] = fresh  # può restare None se il post è stato cancellato

        # Step 4: proietta Post → TimelineItem, scartando i None (post
        # cancellati ma ancora referenziati nello ZSET finché non scade
        # il TTL del sorted set).
        return [
            TimelineItem(
                post_id=p.post_id,
                user_id=p.user_id,
                content=p.content,
                created_at=p.created_at,
                like_count=p.like_count,
            )
            for p in posts
            if p is not None
        ]

    def _rebuild_timeline(
        self, ctx: StrategyContext, viewer_id: int, limit: int
    ) -> list[TimelineItem]:
        """
        Cold-rebuild dello ZSET timeline:{viewer} da PG.

        Carica `_MAX_TIMELINE` voci (NON `limit`) per popolare il sorted set
        per le richieste successive di qualsiasi limit ≤ _MAX_TIMELINE.
        Ritorna però solo le prime `limit` voci al chiamante.

        Cosa va in cache:
          - timeline:{viewer}    → ZSET di post_id con score=timestamp
          - post:{id1}, post:{id2}, … → Post (write-through) così il
                                       prossimo fetch_timeline trova HIT
                                       pieno (ZSET + MGET) senza fallback PG.
        """
        items = feed_repo.query_timeline(
            ctx.read_conn,
            viewer_id=viewer_id,
            window_days=ctx.settings.fyp_recency_window_days,
            limit=_MAX_TIMELINE,
            db_timer=ctx.db_timer,
        )
        if not items:
            return []

        # Popola lo ZSET con post_id come member (NON il JSON completo).
        tl_key = _tl_key(viewer_id)
        id_score_map = {str(it.post_id): it.created_at.timestamp() for it in items}
        ctx.cache.zadd_bulk(
            tl_key, id_score_map, ttl=ctx.settings.cache_ttl_timeline
        )

        # Popola anche `post:{id}` per ogni item caricato. I dati sono
        # già in memoria — sprecato non scriverli ora; il prossimo
        # fetch_timeline troverà HIT pieno senza fallback PG.
        for it in items:
            ctx.cache.set_model(
                Keys.post(it.post_id),
                Post(
                    post_id=it.post_id,
                    user_id=it.user_id,
                    content=it.content,
                    created_at=it.created_at,
                    like_count=it.like_count,
                ),
                ttl=ctx.settings.cache_ttl_post,
            )

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

    # ------------------------------------------------------------------
    # Write hooks
    # ------------------------------------------------------------------

    def on_post_created(
        self, ctx: StrategyContext, author_id: int, post_id: int
    ) -> None:
        # 1. Write-through su `post:{id}` (il nuovo post in cache).
        post = posts_repo.query_post(ctx.conn, post_id, ctx.db_timer)
        if post is None:
            return
        ctx.cache.set_model(
            Keys.post(post_id), post, ttl=ctx.settings.cache_ttl_post
        )

        # 2. Aggiorna il profilo dell'autore (post_count++).
        profile = users_repo.query_user_profile(ctx.conn, author_id, ctx.db_timer)
        if profile is not None:
            ctx.cache.set_model(
                Keys.user(author_id), profile, ttl=ctx.settings.cache_ttl_user
            )

        # 3. Fan-out: aggiungi `str(post_id)` al sorted set di ogni follower.
        follower_ids = _get_follower_ids(ctx, author_id)
        if not follower_ids:
            return

        # Member = post_id come stringa (NON il JSON del TimelineItem).
        # Score = timestamp di created_at per ordinamento DESC al read.
        ctx.cache.zadd_fanout(
            keys=[_tl_key(fid) for fid in follower_ids],
            member=str(post_id),
            score=post.created_at.timestamp(),
            ttl=ctx.settings.cache_ttl_timeline,
            max_size=_MAX_TIMELINE,
        )

    def on_like_added(
        self, ctx: StrategyContext, user_id: int, post_id: int
    ) -> None:
        # Write-through su `post:{id}` — like_count è dentro il Post model.
        # Le timeline NON sono toccate: contengono solo id e il MGET al
        # prossimo read legge il like_count fresco da `post:{id}`.
        post = posts_repo.query_post(ctx.conn, post_id, ctx.db_timer)
        if post is not None:
            ctx.cache.set_model(
                Keys.post(post_id), post, ttl=ctx.settings.cache_ttl_post
            )

    def on_like_removed(
        self, ctx: StrategyContext, user_id: int, post_id: int
    ) -> None:
        post = posts_repo.query_post(ctx.conn, post_id, ctx.db_timer)
        if post is not None:
            ctx.cache.set_model(
                Keys.post(post_id), post, ttl=ctx.settings.cache_ttl_post
            )

    def on_follow_added(
        self, ctx: StrategyContext, follower_id: int, followed_id: int
    ) -> None:
        # La timeline del follower è ora out-of-date (manca i post del
        # nuovo followed). Invalida → rebuild lazy al prossimo fetch_timeline.
        ctx.cache.delete_keys(_tl_key(follower_id))

        # Aggiorna entrambi i profili: 2 query PG sequenziali (come oggi),
        # ma i SET Redis NON sono batched per mantenere il codice semplice
        # e identico alla versione precedente.
        for uid in (follower_id, followed_id):
            profile = users_repo.query_user_profile(ctx.conn, uid, ctx.db_timer)
            if profile is not None:
                ctx.cache.set_model(
                    Keys.user(uid), profile, ttl=ctx.settings.cache_ttl_user
                )

    def on_follow_removed(
        self, ctx: StrategyContext, follower_id: int, followed_id: int
    ) -> None:
        ctx.cache.delete_keys(_tl_key(follower_id))
        for uid in (follower_id, followed_id):
            profile = users_repo.query_user_profile(ctx.conn, uid, ctx.db_timer)
            if profile is not None:
                ctx.cache.set_model(
                    Keys.user(uid), profile, ttl=ctx.settings.cache_ttl_user
                )
