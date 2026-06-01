"""
Registry delle caching strategy.

Aggiungere una nuova strategy in 3 mosse:
  1. Crea `app/strategies/<nome>.py` con `class XxxStrategy(CacheStrategy)`.
  2. Importala qui sotto e aggiungila al dict `STRATEGIES`.
  3. Imposta `CACHE_STRATEGY=<nome>` in `.env` e riavvia uvicorn.

Il nome usato come chiave nel dict è anche il valore che va in `CACHE_STRATEGY`.
"""

from .base import CacheStrategy, StrategyContext
from .cache_aside import CacheAsideStrategy
from .no_cache import NoCacheStrategy
from .hybrid import HybridStrategy

# Registro statico — modificare qui per aggiungere nuove strategy.
STRATEGIES: dict[str, type[CacheStrategy]] = {
    NoCacheStrategy.name: NoCacheStrategy,
    CacheAsideStrategy.name: CacheAsideStrategy,
    HybridStrategy.name: HybridStrategy,
    # Future:
    #   WriteThroughStrategy.name: WriteThroughStrategy,
    #   PushFeedStrategy.name: PushFeedStrategy,
    #   HybridStrategy.name: HybridStrategy,
}


def get_strategy(name: str) -> CacheStrategy:
    """Costruisce la strategy richiesta. Solleva ValueError su nome ignoto."""
    cls = STRATEGIES.get(name)
    if cls is None:
        available = ", ".join(sorted(STRATEGIES.keys()))
        raise ValueError(
            f"Unknown CACHE_STRATEGY '{name}'. Available: {available}"
        )
    return cls()


__all__ = ["CacheStrategy", "StrategyContext", "get_strategy", "STRATEGIES"]
