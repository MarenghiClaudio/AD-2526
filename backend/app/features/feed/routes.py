"""
Endpoint HTTP per la feature feed.

  GET /timeline/{user_id}                            → baseline cronologica
  GET /feed/{user_id}                                → FYP a 1° grado
  GET /feed/{user_id}?with_fof=true                  → FYP esteso al 2° grado

Tutte e tre delegano la logica di lettura alla strategy attiva.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...config import Settings, get_settings
from ...core.responses import ApiResponse, build_response
from ...strategies.base import CacheStrategy, StrategyContext
from ...strategies.deps import get_active_strategy, get_request_context
from ..users import repository as users_repo
from .schemas import FeedResponse, TimelineResponse

router = APIRouter(tags=["feed"])


def _ranking_weights(settings: Settings) -> dict[str, float]:
    """Estrae i parametri di ranking nel formato atteso dalle query SQL."""
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
    strategy: CacheStrategy = Depends(get_active_strategy),
    ctx: StrategyContext = Depends(get_request_context),
    settings: Settings = Depends(get_settings),
    limit: int | None = Query(default=None, ge=1),
) -> ApiResponse[TimelineResponse]:
    """Feed cronologico semplice: i post di chi segui, ordine per data."""
    if not users_repo.user_exists(ctx.conn, user_id, ctx.db_timer):
        raise HTTPException(status_code=404, detail=f"user {user_id} not found")
    items = strategy.fetch_timeline(ctx, user_id, _resolve_limit(limit, settings))
    return build_response(
        TimelineResponse(viewer_id=user_id, items=items),
        request.state.timing,
    )


@router.get("/feed/{user_id}", response_model=ApiResponse[FeedResponse])
def get_feed(
    user_id: int,
    request: Request,
    strategy: CacheStrategy = Depends(get_active_strategy),
    ctx: StrategyContext = Depends(get_request_context),
    settings: Settings = Depends(get_settings),
    limit: int | None = Query(default=None, ge=1),
    with_fof: bool = Query(
        default=False, description="Include follower-of-follower (2nd hop)"
    ),
) -> ApiResponse[FeedResponse]:
    """
    For You Page con ranking ponderato. Se `with_fof=true` include anche
    i post degli utenti seguiti dai miei follow (affinity ridotta).
    """
    if not users_repo.user_exists(ctx.conn, user_id, ctx.db_timer):
        raise HTTPException(status_code=404, detail=f"user {user_id} not found")
    effective_limit = _resolve_limit(limit, settings)
    weights = _ranking_weights(settings)
    if with_fof:
        items = strategy.fetch_fyp_with_fof(ctx, user_id, effective_limit, weights)
    else:
        items = strategy.fetch_fyp(ctx, user_id, effective_limit, weights)
    return build_response(
        FeedResponse(viewer_id=user_id, with_fof=with_fof, items=items),
        request.state.timing,
    )
