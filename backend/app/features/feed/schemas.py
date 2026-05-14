"""Pydantic models per la feature feed."""

from datetime import datetime

from pydantic import BaseModel


class TimelineItem(BaseModel):
    post_id: int
    user_id: int
    content: str
    created_at: datetime
    like_count: int


class FeedItem(BaseModel):
    """Voce del FYP: include lo score di ranking e l'affinity dell'autore."""

    post_id: int
    user_id: int
    content: str
    created_at: datetime
    like_count: int
    affinity: float
    score: float


class FeedResponse(BaseModel):
    viewer_id: int
    with_fof: bool
    items: list[FeedItem]


class TimelineResponse(BaseModel):
    viewer_id: int
    items: list[TimelineItem]
