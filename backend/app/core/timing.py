"""
Utility di timing per misurazioni a granularità sub-millisecondo.

Pattern: ogni endpoint crea un `Timer` per il tempo DB e usa
`time.perf_counter()` per il tempo totale. Le misure finiscono sia nel
body della response (debug) sia nel log strutturato (analisi offline).
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator


class Timer:
    """
    Cronometro cumulativo: più chiamate a `measure()` si sommano.
    Pensato per misurare il tempo totale passato in una risorsa esterna
    (es. DB) anche quando ci sono più query nello stesso endpoint.
    """

    __slots__ = ("_elapsed_seconds",)

    def __init__(self) -> None:
        self._elapsed_seconds: float = 0.0

    @contextmanager
    def measure(self) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self._elapsed_seconds += time.perf_counter() - start

    @property
    def elapsed_seconds(self) -> float:
        return self._elapsed_seconds

    @property
    def elapsed_ms(self) -> float:
        return round(self._elapsed_seconds * 1000.0, 3)


@dataclass
class RequestTiming:
    """
    Container delle misure di una singola request.

    `cache_hit` ha tre stati:
      * None  → la cache non è stata interrogata (es. endpoint di sola scrittura)
      * True  → la prima lookup ha trovato il dato (response servita da cache)
      * False → la prima lookup ha fallito (response servita da DB)

    Lo gestisce `CacheService._record_hit`: solo la PRIMA get sovrascrive None.
    Letture successive (es. get_post dentro fetch_feed) non lo cambiano.
    """

    t0: float = field(default_factory=time.perf_counter)
    db: Timer = field(default_factory=Timer)
    cache: Timer = field(default_factory=Timer)
    cache_hit: bool | None = None

    @property
    def total_ms(self) -> float:
        return round((time.perf_counter() - self.t0) * 1000.0, 3)
