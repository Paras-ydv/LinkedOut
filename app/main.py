"""FastAPI application entrypoint."""

from fastapi import FastAPI

from app.core.config import settings
from app.routers import auth_router, health_router


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
    )

    app.include_router(health_router)
    app.include_router(auth_router)

    return app


app = create_app()
