# Caching Strategies

Modulo che incapsula **come** il backend serve le letture cacheable e **come** reagisce alle scritture. Disaccoppiato dalle route: ogni strategy è una classe che implementa il contratto `CacheStrategy` e viene selezionata via `.env` (`CACHE_STRATEGY=...`).

## Strategie già implementate

| Nome | File | Descrizione |
|---|---|---|
| `no_cache` | [no_cache.py](no_cache.py) | Bypassa Redis. Equivalente alla baseline di Fase 1. Utile come A/B control per le altre strategy. |
| `cache_aside` | [cache_aside.py](cache_aside.py) | Lazy loading + TTL. Invalidazione event-based su `user:{id}` / `post:{id}`. Feed gestiti via TTL (no fan-out). **Default**. |

## Come aggiungere una nuova strategy (workflow per il team)

Tre passi.

### 1. Crea il file della strategia

`backend/app/strategies/<nome>.py`:

```python
from .base import CacheStrategy, StrategyContext
from ..features.users.schemas import UserProfile
from ..features.posts.schemas import Post
from ..features.feed.schemas import TimelineItem, FeedItem


class MiaStrategy(CacheStrategy):
    name = "mia_strategy"  # questa è la chiave usata in CACHE_STRATEGY

    # --- Reads ---

    def get_user_profile(self, ctx: StrategyContext, user_id: int) -> UserProfile | None:
        ...  # la tua logica

    def get_post(self, ctx: StrategyContext, post_id: int) -> Post | None:
        ...

    def fetch_timeline(self, ctx: StrategyContext, viewer_id: int, limit: int) -> list[TimelineItem]:
        ...

    def fetch_fyp(self, ctx: StrategyContext, viewer_id: int, limit: int, weights: dict[str, float]) -> list[FeedItem]:
        ...

    def fetch_fyp_with_fof(self, ctx: StrategyContext, viewer_id: int, limit: int, weights: dict[str, float]) -> list[FeedItem]:
        ...

    # --- Write hooks (chiamati DOPO il commit su PG) ---

    def on_post_created(self, ctx: StrategyContext, author_id: int, post_id: int) -> None:
        ...

    def on_like_added(self, ctx: StrategyContext, user_id: int, post_id: int) -> None:
        ...

    def on_like_removed(self, ctx: StrategyContext, user_id: int, post_id: int) -> None:
        ...

    def on_follow_added(self, ctx: StrategyContext, follower_id: int, followed_id: int) -> None:
        ...

    def on_follow_removed(self, ctx: StrategyContext, follower_id: int, followed_id: int) -> None:
        ...
```

### 2. Registrala

In [`__init__.py`](__init__.py) aggiungi:

```python
from .mia_strategy import MiaStrategy

STRATEGIES = {
    NoCacheStrategy.name: NoCacheStrategy,
    CacheAsideStrategy.name: CacheAsideStrategy,
    MiaStrategy.name: MiaStrategy,   # ← nuova
}
```

### 3. Attivala

In `.env`:

```env
CACHE_STRATEGY=mia_strategy
```

Riavvia uvicorn. Verifica in `/health` o nel log che la strategy attiva sia quella giusta.

## Cosa è disponibile in `StrategyContext`

Ogni metodo della strategy riceve un `StrategyContext` con:

- `ctx.conn` — connessione PostgreSQL (psycopg2) per questa richiesta
- `ctx.cache` — `CacheService` agganciato ai timer della request. Espone:
  - `get_model(key, ModelCls)` / `set_model(key, value, ttl)` per singoli oggetti
  - `get_model_list(key, ModelCls)` / `set_model_list(key, values, ttl)` per liste
  - `delete(*keys)` per invalidazione
- `ctx.db_timer` — `Timer` per misurare il tempo speso in PG (alimenta il `db_ms` della risposta)
- `ctx.settings` — istanza di `Settings` (TTL configurabili, finestre, alpha Pareto, ...)

Le funzioni di "data access pura" sono in `app/features/<feature>/repository.py` — usale come building block quando la tua strategy fa fallback al DB.

## Strategie da provare (suggerite)

| Strategia | Idea principale | File suggerito |
|---|---|---|
| **write_through** | Su `on_*` scrivi sia in cache sia su DB sincronicamente. Consistency stretta, latenza di scrittura raddoppiata. | `write_through.py` |
| **push_feed** | `on_post_created` fa fan-out: `ZADD timeline:{follower}` per ogni follower. `fetch_timeline` legge solo da Redis. | `push_feed.py` |
| **hybrid** | Push per utenti normali, pull (= cache_aside) per le celebrity con > N follower. | `hybrid.py` |
| **write_behind** | Like sincroni su Redis, flush asincrono in batch al DB. Throughput di scrittura altissimo. | `write_behind.py` |

Per ognuna basta la classe nuova nel modulo + la registrazione, **senza toccare le route**.
