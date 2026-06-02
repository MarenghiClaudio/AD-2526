"""
Contratto delle caching strategy.

Ogni strategy implementa **come** servire le letture e **come** reagire alle
scritture. Il backend instrada tutte le operazioni cacheable attraverso una
istanza di `CacheStrategy`; cambiare strategia significa cambiare la classe
attiva via `.env` (CACHE_STRATEGY), senza toccare le route.

Convenzioni:
  * Le funzioni di lettura ritornano direttamente i Pydantic model (o None
    se la risorsa non esiste). La strategy può ottenere il valore da Redis,
    da PG, da una combinazione, o da un altro storage — la route non lo sa.
  * Gli hook `on_*` vengono chiamati DOPO che la scrittura su PG è andata
    a buon fine. Sono il punto in cui la strategy aggiorna/invalida la cache.
    Le scritture sono delegate ai repository (data access), che non parlano
    di cache.

Per aggiungere una nuova strategy (workflow team):
  1. Crea `app/strategies/<nome_strategy>.py` con una classe che implementa
     i metodi di `CacheStrategy` (puoi ereditare da `CacheStrategy` come ABC).
  2. Registrala in `app/strategies/__init__.py` (dict `STRATEGIES`).
  3. Imposta `CACHE_STRATEGY=<nome_strategy>` in `.env` e riavvia.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from psycopg2.extensions import connection as Connection

from ..cache import CacheService
from ..config import Settings
from ..core.timing import Timer

if TYPE_CHECKING:
    from ..features.feed.schemas import FeedItem, TimelineItem
    from ..features.posts.schemas import Post
    from ..features.users.schemas import UserProfile


@dataclass(frozen=True)
class StrategyContext:
    """
    Tutto ciò che la strategy ha a disposizione per una singola operazione.
    Costruito dalla route, passato a ogni metodo della strategy.
    """

    conn: Connection
    cache: CacheService
    db_timer: Timer
    settings: Settings


class CacheStrategy(ABC):
    """
    ABC della caching strategy.

    Le strategie concrete (cache_aside, no_cache, write_through, push_feed, ...)
    sottoclassano questa e sovrascrivono solo i metodi rilevanti.
    """

    # Nome leggibile per logging/debug. Deve combaciare con la chiave usata in
    # CACHE_STRATEGY (vedi registry in __init__.py).
    name: str = "abstract"

    # --- Read operations (cacheable) ---

    @abstractmethod
    def get_user_profile(
        self, ctx: StrategyContext, user_id: int
    ) -> "UserProfile | None": ...

    @abstractmethod
    def get_post(self, ctx: StrategyContext, post_id: int) -> "Post | None": ...

    @abstractmethod
    def fetch_timeline(
        self, ctx: StrategyContext, viewer_id: int, limit: int
    ) -> "list[TimelineItem]": ...

    @abstractmethod
    def fetch_fyp(
        self,
        ctx: StrategyContext,
        viewer_id: int,
        limit: int,
        weights: dict[str, float],
    ) -> "list[FeedItem]": ...

    @abstractmethod
    def fetch_fyp_with_fof(
        self,
        ctx: StrategyContext,
        viewer_id: int,
        limit: int,
        weights: dict[str, float],
    ) -> "list[FeedItem]": ...

    # --- Write hooks (chiamati dopo che PG ha confermato la mutazione) ---

    @abstractmethod
    def on_post_created(
        self, ctx: StrategyContext, author_id: int, post_id: int
    ) -> None: ...

    @abstractmethod
    def on_like_added(
        self, ctx: StrategyContext, user_id: int, post_id: int
    ) -> None: ...

    @abstractmethod
    def on_like_removed(
        self, ctx: StrategyContext, user_id: int, post_id: int
    ) -> None: ...

    @abstractmethod
    def on_follow_added(
        self, ctx: StrategyContext, follower_id: int, followed_id: int
    ) -> None: ...

    @abstractmethod
    def on_follow_removed(
        self, ctx: StrategyContext, follower_id: int, followed_id: int
    ) -> None: ...
