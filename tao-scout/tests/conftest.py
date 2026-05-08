"""Pytest fixtures.

Each test gets an in-memory async SQLite database with the full schema
applied via SQLAlchemy ``create_all`` (we don't run Alembic in tests because
it's not what we're verifying).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Force a deterministic test config before settings is imported.
os.environ.setdefault("TAO_SCOUT_DB_PATH", ":memory-test:")
os.environ.setdefault("TAO_SCOUT_RPC_URL", "wss://test-only.local:443")
os.environ.setdefault("TAO_SCOUT_NETWORK", "test")
os.environ.setdefault("TAO_SCOUT_LOG_LEVEL", "WARNING")


@pytest.fixture
def project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    from tao_scout.db.models import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()
