"""
Envelope di risposta API.

Tutti gli endpoint restituiscono `ApiResponse[T]` per uniformità di parsing
lato client e lato strumenti (Locust). Il campo `timing` è popolato dal
helper `build_response` e contiene le metriche di Livello 1 (per debug).
"""

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel

from .timing import RequestTiming

T = TypeVar("T")


class Timing(BaseModel):
    total_ms: float
    db_ms: float = 0.0
    cache_ms: float = 0.0
    cache_hit: Optional[bool] = None


class ApiResponse(BaseModel, Generic[T]):
    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    timing: Optional[Timing] = None


def _timing(rt: RequestTiming) -> Timing:
    return Timing(
        total_ms=rt.total_ms,
        db_ms=rt.db.elapsed_ms,
        cache_ms=rt.cache.elapsed_ms,
        cache_hit=rt.cache_hit,
    )


def build_response(data: Any, rt: RequestTiming) -> ApiResponse:
    """Costruisce una risposta di successo includendo le metriche di tempo."""
    return ApiResponse(success=True, data=data, timing=_timing(rt))


def build_error(error: str, rt: RequestTiming) -> ApiResponse:
    """Costruisce una risposta di errore con timing (utile per benchmark)."""
    return ApiResponse(success=False, error=error, timing=_timing(rt))
