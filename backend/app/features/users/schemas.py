"""Pydantic models per il modulo users."""

from datetime import datetime

from pydantic import BaseModel


class UserProfile(BaseModel):
    user_id: int
    username: str
    created_at: datetime
    post_count: int
    follower_count: int
    following_count: int
