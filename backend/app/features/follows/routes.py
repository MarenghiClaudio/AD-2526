"""Endpoint HTTP per la feature follows."""

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2.extensions import connection as Connection

from ...core.request_state import start_timing
from ...core.responses import ApiResponse, build_response
from ...db import get_db
from ..users import repository as users_repo
from . import repository
from .schemas import FollowMutationResponse, FollowRequest

router = APIRouter(prefix="/follows", tags=["follows"])


def _validate_actors(db: Connection, follower_id: int, followed_id: int) -> None:
    if not users_repo.user_exists(db, follower_id):
        raise HTTPException(status_code=404, detail=f"user {follower_id} not found")
    if not users_repo.user_exists(db, followed_id):
        raise HTTPException(status_code=404, detail=f"user {followed_id} not found")


@router.post("", response_model=ApiResponse[FollowMutationResponse])
def add_follow(
    payload: FollowRequest,
    request: Request,
    db: Connection = Depends(get_db),
) -> ApiResponse[FollowMutationResponse]:
    """Crea una relazione di follow (idempotente)."""
    rt = start_timing(request)
    with rt.db.measure():
        _validate_actors(db, payload.follower_id, payload.followed_id)
        created = repository.add_follow(db, payload.follower_id, payload.followed_id)
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
) -> ApiResponse[FollowMutationResponse]:
    """Rimuove una relazione di follow (idempotente)."""
    rt = start_timing(request)
    with rt.db.measure():
        deleted = repository.remove_follow(db, payload.follower_id, payload.followed_id)
    return build_response(
        FollowMutationResponse(
            follower_id=payload.follower_id,
            followed_id=payload.followed_id,
            created=False,
            deleted=deleted,
        ),
        rt,
    )
