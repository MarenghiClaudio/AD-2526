"""Pydantic models per la feature follows."""

from pydantic import BaseModel, model_validator


class FollowRequest(BaseModel):
    follower_id: int
    followed_id: int

    @model_validator(mode="after")
    def _no_self_follow(self) -> "FollowRequest":
        if self.follower_id == self.followed_id:
            raise ValueError("follower_id and followed_id must be different")
        return self


class FollowMutationResponse(BaseModel):
    follower_id: int
    followed_id: int
    created: bool
    deleted: bool
