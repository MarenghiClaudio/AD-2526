"""Endpoint HTTP per la feature follows."""

from fastapi import APIRouter, Depends, HTTPException, Request

from ...core.responses import ApiResponse, build_response
from ...strategies.base import CacheStrategy, StrategyContext
from ...strategies.deps import get_active_strategy, get_request_context
from ..users import repository as users_repo
from . import repository
from .schemas import FollowMutationResponse, FollowRequest

router = APIRouter(prefix="/follows", tags=["follows"])


def _validate_actors(
    ctx: StrategyContext, follower_id: int, followed_id: int
) -> None:
    if not users_repo.user_exists(ctx.conn, follower_id, ctx.db_timer):
        raise HTTPException(status_code=404, detail=f"user {follower_id} not found")
    if not users_repo.user_exists(ctx.conn, followed_id, ctx.db_timer):
        raise HTTPException(status_code=404, detail=f"user {followed_id} not found")


@router.post("", response_model=ApiResponse[FollowMutationResponse])
def add_follow(
    payload: FollowRequest,
    request: Request,
    strategy: CacheStrategy = Depends(get_active_strategy),
    ctx: StrategyContext = Depends(get_request_context),
) -> ApiResponse[FollowMutationResponse]:
    """Crea una relazione di follow (idempotente)."""
    _validate_actors(ctx, payload.follower_id, payload.followed_id)
    created = repository.insert_follow(
        ctx.conn, payload.follower_id, payload.followed_id, ctx.db_timer
    )
    if created:
        strategy.on_follow_added(ctx, payload.follower_id, payload.followed_id)
    return build_response(
        FollowMutationResponse(
            follower_id=payload.follower_id,
            followed_id=payload.followed_id,
            created=created,
            deleted=False,
        ),
        request.state.timing,
    )


@router.delete("", response_model=ApiResponse[FollowMutationResponse])
def remove_follow(
    payload: FollowRequest,
    request: Request,
    strategy: CacheStrategy = Depends(get_active_strategy),
    ctx: StrategyContext = Depends(get_request_context),
) -> ApiResponse[FollowMutationResponse]:
    """Rimuove una relazione di follow (idempotente)."""
    deleted = repository.delete_follow(
        ctx.conn, payload.follower_id, payload.followed_id, ctx.db_timer
    )
    if deleted:
        strategy.on_follow_removed(ctx, payload.follower_id, payload.followed_id)
    return build_response(
        FollowMutationResponse(
            follower_id=payload.follower_id,
            followed_id=payload.followed_id,
            created=False,
            deleted=deleted,
        ),
        request.state.timing,
    )
