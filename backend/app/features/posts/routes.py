"""Endpoint HTTP per la feature posts."""

import redis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from psycopg2.extensions import connection as Connection

from ...cache import CacheService, get_cache_client
from ...config import Settings, get_settings
from ...core.request_state import start_timing
from ...core.responses import ApiResponse, build_response
from ...db import get_db
from ..users import repository as users_repo
from . import repository
from .schemas import CreatePostRequest, CreatePostResponse, Post

router = APIRouter(prefix="/posts", tags=["posts"])


@router.get("/{post_id}", response_model=ApiResponse[Post])
def get_post(
    post_id: int,
    request: Request,
    db: Connection = Depends(get_db),
    redis_client: redis.Redis = Depends(get_cache_client),
    settings: Settings = Depends(get_settings),
) -> ApiResponse[Post]:
    """Singolo post con like_count aggregato."""
    rt = start_timing(request)
    cache = CacheService(redis_client, rt, enabled=settings.cache_enabled)
    post = repository.get_post(db, post_id, cache, rt.db)
    if post is None:
        raise HTTPException(status_code=404, detail=f"post {post_id} not found")
    return build_response(post, rt)


@router.post(
    "",
    response_model=ApiResponse[CreatePostResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_post(
    payload: CreatePostRequest,
    request: Request,
    db: Connection = Depends(get_db),
    redis_client: redis.Redis = Depends(get_cache_client),
    settings: Settings = Depends(get_settings),
) -> ApiResponse[CreatePostResponse]:
    """Crea un nuovo post per conto di user_id."""
    rt = start_timing(request)
    cache = CacheService(redis_client, rt, enabled=settings.cache_enabled)
    if not users_repo.user_exists(db, payload.user_id, rt.db):
        raise HTTPException(status_code=404, detail=f"user {payload.user_id} not found")
    created = repository.create_post(db, payload.user_id, payload.content, cache, rt.db)
    return build_response(created, rt)
