"""Endpoint HTTP per la feature posts."""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ...core.responses import ApiResponse, build_response
from ...strategies.base import CacheStrategy, StrategyContext
from ...strategies.deps import get_active_strategy, get_request_context
from ..users import repository as users_repo
from . import repository
from .schemas import CreatePostRequest, CreatePostResponse, Post

router = APIRouter(prefix="/posts", tags=["posts"])


@router.get("/{post_id}", response_model=ApiResponse[Post])
def get_post(
    post_id: int,
    request: Request,
    strategy: CacheStrategy = Depends(get_active_strategy),
    ctx: StrategyContext = Depends(get_request_context),
) -> ApiResponse[Post]:
    """Singolo post con like_count aggregato."""
    post = strategy.get_post(ctx, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail=f"post {post_id} not found")
    return build_response(post, request.state.timing)


@router.post(
    "",
    response_model=ApiResponse[CreatePostResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_post(
    payload: CreatePostRequest,
    request: Request,
    strategy: CacheStrategy = Depends(get_active_strategy),
    ctx: StrategyContext = Depends(get_request_context),
) -> ApiResponse[CreatePostResponse]:
    """Crea un nuovo post per conto di user_id."""
    if not users_repo.user_exists(ctx.read_conn, payload.user_id, ctx.db_timer):
        raise HTTPException(status_code=404, detail=f"user {payload.user_id} not found")
    created = repository.insert_post(
        ctx.conn, payload.user_id, payload.content, ctx.db_timer
    )
    strategy.on_post_created(ctx, payload.user_id, created.post_id)
    return build_response(created, request.state.timing)
