"""
Database configuration and session management
"""
from typing import AsyncGenerator
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from ..core.config import settings

# Create async engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    pool_pre_ping=True,
    pool_size=20,  # Increased for multiple workers
    max_overflow=40,  # Increased for peak load
    # Recycle conns idle longer than 30min so we never hand out a stale
    # connection that PG (or a load balancer) has already closed.
    pool_recycle=1800,
    # asyncpg connect_args: cap every query at 60s so a runaway SELECT
    # cannot stall a request indefinitely; matches the socket timeout
    # used by gspread.
    connect_args={
        "server_settings": {
            "statement_timeout": "60000",            # 60 seconds (ms)
            "lock_timeout": "30000",                 # 30 seconds (ms)
            "idle_in_transaction_session_timeout": "300000",  # 5 min (ms)
            "application_name": "datainfo-backend",
        },
        "timeout": 10,  # connection-establishment timeout, seconds
    },
)

# Create session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False
)

# Base class for models
Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency to get database session.
    
    Yields:
        Database session
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Close database connections."""
    await engine.dispose()
