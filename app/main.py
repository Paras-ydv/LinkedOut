"""FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

    # CORS: `settings.cors_allowed_origins` defaults to `["*"]` for local
    # dev/portfolio-demo convenience. A real deployment MUST set
    # `CORS_ALLOWED_ORIGINS` to the exact frontend origin(s) — wildcard
    # origins are especially dangerous here because several routes accept
    # a bearer token (`Authorization` header), and this app's whole premise
    # is that a leaked token must not become a way to exfiltrate anonymous-
    # reviewer data cross-origin. `allow_credentials=True` is deliberately
    # NOT set (this API uses bearer tokens, not cookies, so there's no
    # session cookie for a browser to attach) — combining `allow_origins=
    # ["*"]` with `allow_credentials=True` is a known CORS misconfiguration
    # the Starlette/FastAPI docs explicitly warn against, and this app
    # never needs that combination in the first place. See
    # TRUST_ARCHITECTURE.md for the full writeup.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
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
