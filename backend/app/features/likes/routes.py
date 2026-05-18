"""Endpoint HTTP per la feature likes."""

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
from .schemas import LikeMutationResponse, LikeRequest

router = APIRouter(prefix="/likes", tags=["likes"])


def _validate_actors(
    db: Connection, user_id: int, post_id: int, db_timer: Timer
) -> None:
    """Verifica esistenza di utente e post prima di mutare."""
    if not users_repo.user_exists(db, user_id, db_timer):
        raise HTTPException(status_code=404, detail=f"user {user_id} not found")
    if not repository.post_exists(db, post_id, db_timer):
        raise HTTPException(status_code=404, detail=f"post {post_id} not found")


@router.post("", response_model=ApiResponse[LikeMutationResponse])
def add_like(
    payload: LikeRequest,
    request: Request,
    db: Connection = Depends(get_db),
    redis_client: redis.Redis = Depends(get_cache_client),
    settings: Settings = Depends(get_settings),
) -> ApiResponse[LikeMutationResponse]:
    """Aggiunge un like (idempotente)."""
    rt = start_timing(request)
    cache = CacheService(redis_client, rt, enabled=settings.cache_enabled)
    _validate_actors(db, payload.user_id, payload.post_id, rt.db)
    created = repository.add_like(db, payload.user_id, payload.post_id, cache, rt.db)
    return build_response(
        LikeMutationResponse(
            user_id=payload.user_id,
            post_id=payload.post_id,
            created=created,
            deleted=False,
        ),
        rt,
    )


@router.delete("", response_model=ApiResponse[LikeMutationResponse])
def remove_like(
    payload: LikeRequest,
    request: Request,
    db: Connection = Depends(get_db),
    redis_client: redis.Redis = Depends(get_cache_client),
    settings: Settings = Depends(get_settings),
) -> ApiResponse[LikeMutationResponse]:
    """Rimuove un like (idempotente)."""
    rt = start_timing(request)
    cache = CacheService(redis_client, rt, enabled=settings.cache_enabled)
    deleted = repository.remove_like(db, payload.user_id, payload.post_id, cache, rt.db)
    return build_response(
        LikeMutationResponse(
            user_id=payload.user_id,
            post_id=payload.post_id,
            created=False,
            deleted=deleted,
        ),
        rt,
    )
