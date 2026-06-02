"""Endpoint HTTP per la feature likes."""

from fastapi import APIRouter, Depends, HTTPException, Request

from ...core.responses import ApiResponse, build_response
from ...strategies.base import CacheStrategy, StrategyContext
from ...strategies.deps import get_active_strategy, get_request_context
from ..users import repository as users_repo
from . import repository
from .schemas import LikeMutationResponse, LikeRequest

router = APIRouter(prefix="/likes", tags=["likes"])


def _validate_actors(ctx: StrategyContext, user_id: int, post_id: int) -> None:
    if not users_repo.user_exists(ctx.conn, user_id, ctx.db_timer):
        raise HTTPException(status_code=404, detail=f"user {user_id} not found")
    if not repository.post_exists(ctx.conn, post_id, ctx.db_timer):
        raise HTTPException(status_code=404, detail=f"post {post_id} not found")


@router.post("", response_model=ApiResponse[LikeMutationResponse])
def add_like(
    payload: LikeRequest,
    request: Request,
    strategy: CacheStrategy = Depends(get_active_strategy),
    ctx: StrategyContext = Depends(get_request_context),
) -> ApiResponse[LikeMutationResponse]:
    """Aggiunge un like (idempotente)."""
    _validate_actors(ctx, payload.user_id, payload.post_id)
    created = repository.insert_like(
        ctx.conn, payload.user_id, payload.post_id, ctx.db_timer
    )
    if created:
        strategy.on_like_added(ctx, payload.user_id, payload.post_id)
    return build_response(
        LikeMutationResponse(
            user_id=payload.user_id,
            post_id=payload.post_id,
            created=created,
            deleted=False,
        ),
        request.state.timing,
    )


@router.delete("", response_model=ApiResponse[LikeMutationResponse])
def remove_like(
    payload: LikeRequest,
    request: Request,
    strategy: CacheStrategy = Depends(get_active_strategy),
    ctx: StrategyContext = Depends(get_request_context),
) -> ApiResponse[LikeMutationResponse]:
    """Rimuove un like (idempotente)."""
    deleted = repository.delete_like(
        ctx.conn, payload.user_id, payload.post_id, ctx.db_timer
    )
    if deleted:
        strategy.on_like_removed(ctx, payload.user_id, payload.post_id)
    return build_response(
        LikeMutationResponse(
            user_id=payload.user_id,
            post_id=payload.post_id,
            created=False,
            deleted=deleted,
        ),
        request.state.timing,
    )
