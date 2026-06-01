"""Endpoint HTTP per la feature users."""

from fastapi import APIRouter, Depends, HTTPException, Request

from ...core.responses import ApiResponse, build_response
from ...strategies.base import CacheStrategy, StrategyContext
from ...strategies.deps import get_active_strategy, get_request_context
from .schemas import UserProfile

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}", response_model=ApiResponse[UserProfile])
def get_user(
    user_id: int,
    request: Request,
    strategy: CacheStrategy = Depends(get_active_strategy),
    ctx: StrategyContext = Depends(get_request_context),
) -> ApiResponse[UserProfile]:
    """Profilo utente: dati anagrafici + counter aggregati (post, follower, following)."""
    profile = strategy.get_user_profile(ctx, user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"user {user_id} not found")
    return build_response(profile, request.state.timing)
