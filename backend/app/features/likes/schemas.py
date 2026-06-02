"""Pydantic models per la feature likes."""

from pydantic import BaseModel


class LikeRequest(BaseModel):
    user_id: int
    post_id: int


class LikeMutationResponse(BaseModel):
    user_id: int
    post_id: int
    created: bool  # True su POST se la riga è stata inserita, False se già esisteva
    deleted: bool  # True su DELETE se la riga è stata rimossa, False se non c'era
