from collections.abc import AsyncIterator
import logging

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..config import settings

logger = logging.getLogger(__name__)


class DatabasePool:
    def __init__(self) -> None:
        self.engine: AsyncEngine | None = None
        self.session_factory: async_sessionmaker[AsyncSession] | None = None

    async def initialize(self) -> None:
        """Initialize database connection pool."""
        if self.session_factory is not None:
            return

        try:
            database_url = settings.database_url
            if database_url.startswith("postgresql://"):
                database_url = database_url.replace(
                    "postgresql://", "postgresql+asyncpg://", 1
                )

            self.engine = create_async_engine(
                database_url,
                pool_size=settings.database_pool_size,
                max_overflow=settings.database_max_overflow,
                pool_timeout=settings.database_pool_timeout,
                pool_pre_ping=True,
                pool_recycle=settings.database_pool_recycle,
                echo=False,
            )

            self.session_factory = async_sessionmaker(
                bind=self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            logger.info("Database connection pool initialized")
        except Exception:
            logger.exception("Database pool initialization failed")
            self.engine = None
            self.session_factory = None
            raise

    async def close(self) -> None:
        """Close database connections."""
        if self.engine:
            await self.engine.dispose()
            self.engine = None
            self.session_factory = None

    def get_session(self) -> AsyncSession:
        """Get database session from pool."""
        session_factory = self.session_factory
        if session_factory is None:
            raise RuntimeError("Database pool not initialized")
        return session_factory()


db_pool = DatabasePool()


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Dependency to get database session."""
    async with db_pool.get_session() as session:
        yield session
