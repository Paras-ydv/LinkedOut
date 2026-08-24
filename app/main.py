"""FastAPI application entrypoint."""

from fastapi import FastAPI

from app.core.config import settings
from app.routers import (
    auth_router,
    companies_router,
    employer_router,
    health_router,
    layoff_events_router,
    reviews_router,
)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
    )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(reviews_router)
    app.include_router(layoff_events_router)
    app.include_router(employer_router)
    app.include_router(companies_router)

    return app


app = create_app()
