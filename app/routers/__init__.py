from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.companies import router as companies_router
from app.routers.employer import router as employer_router
from app.routers.grievance import router as grievance_router
from app.routers.health import router as health_router
from app.routers.layoff_events import router as layoff_events_router
from app.routers.reviews import router as reviews_router
from app.routers.takedown import admin_router as takedown_admin_router
from app.routers.takedown import router as takedown_router

__all__ = [
    "health_router",
    "auth_router",
    "reviews_router",
    "layoff_events_router",
    "employer_router",
    "companies_router",
    "admin_router",
    "takedown_router",
    "takedown_admin_router",
    "grievance_router",
]
