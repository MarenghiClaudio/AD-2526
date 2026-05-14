"""Pydantic models per la feature posts."""

from datetime import datetime

from pydantic import BaseModel, Field


class Post(BaseModel):
    post_id: int
    user_id: int
    content: str
    created_at: datetime
    like_count: int = 0


class CreatePostRequest(BaseModel):
    user_id: int
    content: str = Field(min_length=1, max_length=2000)


class CreatePostResponse(BaseModel):
    post_id: int
    user_id: int
    content: str
    created_at: datetime
