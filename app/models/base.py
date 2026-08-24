"""Declarative base shared by all ORM models.

Alembic's `env.py` imports `Base.metadata` (via `app.models`) to drive
autogenerate, so every model module must be imported in
`app/models/__init__.py` or autogenerate will silently miss it.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
