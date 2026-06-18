"""
Entry point dell'app FastAPI.

  uvicorn app.main:app --reload
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI

from . import cache as cache_module
from .config import Settings, get_settings
from .db import close_pool, close_read_pools, init_pool, init_read_pools
from .features.feed.routes import router as feed_router
from .features.follows.routes import router as follows_router
from .features.likes.routes import router as likes_router
from .features.posts.routes import router as posts_router
from .features.users.routes import router as users_router
from .middleware.request_logger import close_sink, request_logging_middleware


def _configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Inizializzazione dei pool al boot, cleanup allo shutdown."""
    _configure_logging()
    init_pool()
    init_read_pools()
    cache_module.init_pool()
    try:
        yield
    finally:
        cache_module.close_pool()
        close_read_pools()
        close_pool()
        close_sink()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Social Network API — Fase 1 baseline",
        description=(
            "Backend HTTP per benchmark di caching. In Fase 1 le query "
            "vanno direttamente su PostgreSQL; in Fase 2 i repository "
            "verranno estesi con un layer Redis."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # Middleware di logging strutturato per ogni richiesta.
    app.middleware("http")(request_logging_middleware)

    # Wiring dei router per feature.
    app.include_router(users_router)
    app.include_router(posts_router)
    app.include_router(likes_router)
    app.include_router(follows_router)
    app.include_router(feed_router)

    @app.get("/health", tags=["meta"])
    def health(settings: Settings = Depends(get_settings)) -> dict[str, str]:
        """Smoke-check usato anche dai container orchestrator."""
        return {
            "status": "ok",
            "cache_strategy": settings.cache_strategy,
        }

    return app


app = create_app()
