"""Endpoint HTTP per la feature follows."""

import redis
from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2.extensions import connection as Connection

from ...cache import CacheService, get_cache_client
from ...config import Settings, get_settings
from ...core.request_state import start_timing
from ...core.responses import ApiResponse, build_response
from ...core.timing import Timer
from ...db import get_db
from ..users import repository as users_repo
from . import repository
from .schemas import FollowMutationResponse, FollowRequest

router = APIRouter(prefix="/follows", tags=["follows"])


def _validate_actors(
    db: Connection, follower_id: int, followed_id: int, db_timer: Timer
) -> None:
    if not users_repo.user_exists(db, follower_id, db_timer):
        raise HTTPException(status_code=404, detail=f"user {follower_id} not found")
    if not users_repo.user_exists(db, followed_id, db_timer):
        raise HTTPException(status_code=404, detail=f"user {followed_id} not found")


@router.post("", response_model=ApiResponse[FollowMutationResponse])
def add_follow(
    payload: FollowRequest,
    request: Request,
    db: Connection = Depends(get_db),
    redis_client: redis.Redis = Depends(get_cache_client),
    settings: Settings = Depends(get_settings),
) -> ApiResponse[FollowMutationResponse]:
    """Crea una relazione di follow (idempotente)."""
    rt = start_timing(request)
    cache = CacheService(redis_client, rt, enabled=settings.cache_enabled)
    _validate_actors(db, payload.follower_id, payload.followed_id, rt.db)
    created = repository.add_follow(
        db, payload.follower_id, payload.followed_id, cache, rt.db
    )
    return build_response(
        FollowMutationResponse(
            follower_id=payload.follower_id,
            followed_id=payload.followed_id,
            created=created,
            deleted=False,
        ),
        rt,
    )


@router.delete("", response_model=ApiResponse[FollowMutationResponse])
def remove_follow(
    payload: FollowRequest,
    request: Request,
    db: Connection = Depends(get_db),
    redis_client: redis.Redis = Depends(get_cache_client),
    settings: Settings = Depends(get_settings),
) -> ApiResponse[FollowMutationResponse]:
    """Rimuove una relazione di follow (idempotente)."""
    rt = start_timing(request)
    cache = CacheService(redis_client, rt, enabled=settings.cache_enabled)
    deleted = repository.remove_follow(
        db, payload.follower_id, payload.followed_id, cache, rt.db
    )
    return build_response(
        FollowMutationResponse(
            follower_id=payload.follower_id,
            followed_id=payload.followed_id,
            created=False,
            deleted=deleted,
        ),
        rt,
    )
