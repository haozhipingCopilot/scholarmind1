"""
MySQL async engine and session factory.
Used by services (parsing, indexing) and the RQ worker.
"""
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from common.config import settings

DATABASE_URL = (
    f"mysql+aiomysql://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}"
    f"@{settings.MYSQL_HOST}:{settings.MYSQL_PORT}/{settings.MYSQL_DB}"
    "?charset=utf8mb4"
)

engine = create_async_engine(
    DATABASE_URL,
    pool_size=settings.MYSQL_POOL_SIZE,
    max_overflow=10,
    pool_recycle=3600,
    echo=False,
)

_AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def get_db_session():
    """Async context manager that yields a session, commits on exit, rolls back on error."""
    async with _AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
