"""
Async SQLAlchemy database setup.

Uses aiosqlite for development (SQLite) and asyncpg for production (PostgreSQL).
Switch by changing DATABASE_URL in environment.
"""

import os
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./iftr.db"
)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    # SQLite-specific: allow same connection across threads
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    """FastAPI dependency that yields a database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """Create all tables. Called once on app startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
