from sqlalchemy.ext.asyncio import create_async_engine, AsyncConnection
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    echo=False,
)


@asynccontextmanager
async def get_db_connection() -> AsyncGenerator[AsyncConnection, None]:
    """Yield an async database connection."""
    async with engine.connect() as conn:
        yield conn


async def dispose_engine() -> None:
    """Dispose of the engine's connection pool."""
    await engine.dispose()
