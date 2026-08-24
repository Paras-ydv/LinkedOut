"""Shared pytest fixtures.

Tests run against a real Postgres (set via DATABASE_URL, e.g. the
`linkedout_test` database) — not sqlite — because the app relies on
Postgres-specific features (native ENUM types, ARRAY columns) that sqlite
doesn't support.

Everything (engine, schema, session) is created fresh per test function and
torn down at the end of it. That's slower than sharing an engine across the
session, but async engines/connections are bound to the event loop they
were created on, and pytest-asyncio gives each test function its own loop
by default — a session-scoped engine fixture breaks with cross-loop errors
unless every fixture and test is pinned to the same loop scope. Function
scope sidesteps that entirely; revisit if the test suite grows large enough
for per-test schema setup to matter for speed.
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models import Base

if "test" not in settings.database_url:
    raise RuntimeError(
        "DATABASE_URL does not look like a test database "
        f"({settings.database_url!r}). Refusing to run tests that create/drop "
        "tables against what might be a real database."
    )


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    test_engine = create_async_engine(settings.database_url, future=True)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def _get_db_override() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
