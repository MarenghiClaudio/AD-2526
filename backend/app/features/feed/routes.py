"""
Endpoint HTTP per la feature feed.

Tre endpoint:
  GET /timeline/{user_id}                            → baseline cronologica
  GET /feed/{user_id}                                → FYP a 1° grado (default)
  GET /feed/{user_id}?with_fof=true                  → FYP esteso al 2° grado

Tenere `/feed/{user_id}` come unico endpoint con parametro `with_fof` rende
i benchmark direttamente confrontabili (stessa risorsa, stesso parsing
lato Locust, differenza nei soli numeri).
"""

import redis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg2.extensions import connection as Connection

from ...cache import CacheService, get_cache_client
from ...config import Settings, get_settings
from ...core.request_state import start_timing
from ...core.responses import ApiResponse, build_response
from ...db import get_db
from ..users import repository as users_repo
from . import repository
from .schemas import FeedResponse, TimelineResponse

router = APIRouter(tags=["feed"])


def _ranking_weights(settings: Settings) -> dict[str, float]:
    """Estrae i parametri di ranking nel formato atteso dal repository."""
    return {
        "w_recency": settings.fyp_weight_recency,
        "w_affinity": settings.fyp_weight_affinity,
        "w_popularity": settings.fyp_weight_popularity,
        "tau_sec": settings.fyp_recency_tau_seconds,
        "affinity_direct": settings.fyp_affinity_direct,
        "affinity_fof": settings.fyp_affinity_fof,
    }


def _resolve_limit(requested: int | None, settings: Settings) -> int:
    if requested is None:
        return settings.fyp_default_limit
    return max(1, min(requested, settings.fyp_max_limit))


@router.get("/timeline/{user_id}", response_model=ApiResponse[TimelineResponse])
def get_timeline(
    user_id: int,
    request: Request,
    db: Connection = Depends(get_db),
    redis_client: redis.Redis = Depends(get_cache_client),
    settings: Settings = Depends(get_settings),
    limit: int | None = Query(default=None, ge=1),
) -> ApiResponse[TimelineResponse]:
    """Feed cronologico semplice: i post di chi segui, ordine per data."""
    rt = start_timing(request)
    cache = CacheService(redis_client, rt, enabled=settings.cache_enabled)
    effective_limit = _resolve_limit(limit, settings)
    if not users_repo.user_exists(db, user_id, rt.db):
        raise HTTPException(status_code=404, detail=f"user {user_id} not found")
    items = repository.fetch_timeline(
        db,
        viewer_id=user_id,
        window_days=settings.fyp_recency_window_days,
        limit=effective_limit,
        cache=cache,
        db_timer=rt.db,
    )
    return build_response(TimelineResponse(viewer_id=user_id, items=items), rt)


@router.get("/feed/{user_id}", response_model=ApiResponse[FeedResponse])
def get_feed(
    user_id: int,
    request: Request,
    db: Connection = Depends(get_db),
    redis_client: redis.Redis = Depends(get_cache_client),
    settings: Settings = Depends(get_settings),
    limit: int | None = Query(default=None, ge=1),
    with_fof: bool = Query(default=False, description="Include follower-of-follower (2nd hop)"),
) -> ApiResponse[FeedResponse]:
    """
    For You Page con ranking ponderato. Se `with_fof=true` include anche
    i post degli utenti seguiti dai miei follow (affinity ridotta).
    """
    rt = start_timing(request)
    cache = CacheService(redis_client, rt, enabled=settings.cache_enabled)
    effective_limit = _resolve_limit(limit, settings)
    weights = _ranking_weights(settings)
    if not users_repo.user_exists(db, user_id, rt.db):
        raise HTTPException(status_code=404, detail=f"user {user_id} not found")
    fetch = repository.fetch_fyp_with_fof if with_fof else repository.fetch_fyp
    items = fetch(
        db,
        viewer_id=user_id,
        window_days=settings.fyp_recency_window_days,
        limit=effective_limit,
        weights=weights,
        cache=cache,
        db_timer=rt.db,
    )
    return build_response(
        FeedResponse(viewer_id=user_id, with_fof=with_fof, items=items),
        rt,
    )
