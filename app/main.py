"""FastAPI application entrypoint."""

from fastapi import FastAPI

from app.core.config import settings
from app.core.logging import configure_logging
from app.routers import (
    admin_router,
    auth_router,
    companies_router,
    employer_router,
    grievance_router,
    health_router,
    layoff_events_router,
    reviews_router,
    takedown_admin_router,
    takedown_router,
)


def create_app() -> FastAPI:
    configure_logging()

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
    app.include_router(admin_router)
    app.include_router(takedown_router)
    app.include_router(takedown_admin_router)
    app.include_router(grievance_router)

    return app


app = create_app()
