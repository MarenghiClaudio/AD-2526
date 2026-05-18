"""Endpoint HTTP per la feature users."""

import redis
from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2.extensions import connection as Connection

from ...cache import CacheService, get_cache_client
from ...config import Settings, get_settings
from ...core.request_state import start_timing
from ...core.responses import ApiResponse, build_response
from ...db import get_db
from . import repository
from .schemas import UserProfile

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}", response_model=ApiResponse[UserProfile])
def get_user(
    user_id: int,
    request: Request,
    db: Connection = Depends(get_db),
    redis_client: redis.Redis = Depends(get_cache_client),
    settings: Settings = Depends(get_settings),
) -> ApiResponse[UserProfile]:
    """Profilo utente: dati anagrafici + counter aggregati (post, follower, following)."""
    rt = start_timing(request)
    cache = CacheService(redis_client, rt, enabled=settings.cache_enabled)
    profile = repository.get_user_profile(db, user_id, cache, rt.db)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"user {user_id} not found")
    return build_response(profile, rt)
