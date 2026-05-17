"""Endpoint HTTP per la feature likes."""

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2.extensions import connection as Connection

from ...core.request_state import start_timing
from ...core.responses import ApiResponse, build_response
from ...db import get_db
from ..users import repository as users_repo
from . import repository
from .schemas import LikeMutationResponse, LikeRequest


router = APIRouter(prefix="/likes", tags=["likes"])


def _validate_actors(db: Connection, user_id: int, post_id: int) -> None:
    """Verifica esistenza di utente e post prima di mutare."""
    if not users_repo.user_exists(db, user_id):
        raise HTTPException(status_code=404, detail=f"user {user_id} not found")
    if not repository.post_exists(db, post_id):
        raise HTTPException(status_code=404, detail=f"post {post_id} not found")


@router.post("", response_model=ApiResponse[LikeMutationResponse])
def add_like(
    payload: LikeRequest,
    request: Request,
    db: Connection = Depends(get_db),
) -> ApiResponse[LikeMutationResponse]:
    """Aggiunge un like (idempotente)."""
    rt = start_timing(request)
    with rt.db.measure():
        _validate_actors(db, payload.user_id, payload.post_id)
        created = repository.add_like(db, payload.user_id, payload.post_id)

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
) -> ApiResponse[LikeMutationResponse]:
    """Rimuove un like (idempotente)."""
    rt = start_timing(request)
    with rt.db.measure():
        deleted = repository.remove_like(db, payload.user_id, payload.post_id)
    return build_response(
        LikeMutationResponse(
            user_id=payload.user_id,
            post_id=payload.post_id,
            created=False,
            deleted=deleted,
        ),
        rt,
    )
