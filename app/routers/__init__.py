from app.routers.auth import router as auth_router
from app.routers.employer import router as employer_router
from app.routers.health import router as health_router
from app.routers.layoff_events import router as layoff_events_router
from app.routers.reviews import router as reviews_router

__all__ = [
    "health_router",
    "auth_router",
    "reviews_router",
    "layoff_events_router",
    "employer_router",
]
