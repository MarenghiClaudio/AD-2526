"""Endpoint HTTP per la feature posts."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from psycopg2.extensions import connection as Connection

from ...core.request_state import start_timing
from ...core.responses import ApiResponse, build_response
from ...db import get_db
from ..users import repository as users_repo
from ..users.repository import invalidate_user_profile
from ..feed.repository import invalidate_feed
from ..follows.repository import get_follower_ids
from . import repository
from .schemas import CreatePostRequest, CreatePostResponse, Post

router = APIRouter(prefix="/posts", tags=["posts"])


@router.get("/{post_id}", response_model=ApiResponse[Post])
def get_post(
    post_id: int,
    request: Request,
    db: Connection = Depends(get_db),
) -> ApiResponse[Post]:
    """Singolo post con like_count aggregato."""
    rt = start_timing(request)
    with rt.db.measure():
        post = repository.get_post(db, post_id)
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
) -> ApiResponse[CreatePostResponse]:
    """Crea un nuovo post per conto di user_id."""
    rt = start_timing(request)
    with rt.db.measure():
        if not users_repo.user_exists(db, payload.user_id):
            raise HTTPException(status_code=404, detail=f"user {payload.user_id} not found")
        created = repository.create_post(db, payload.user_id, payload.content)
        follower_ids = get_follower_ids(db, payload.user_id)
    invalidate_user_profile(payload.user_id)
    for fid in follower_ids:
        invalidate_feed(fid)
    return build_response(created, rt)
