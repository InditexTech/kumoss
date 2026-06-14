# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Database session management with connection pooling."""

from typing import AsyncGenerator, Optional
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool
from sqlalchemy import text

from src.shared.logger import logging
from src.shared.exceptions import ExceptionHandler
from src.infrastructure.database.config import db_config


class SessionManager:
    """Manages database sessions and connection pooling."""

    def __init__(self):
        self._engine: Optional[AsyncEngine] = None
        self._sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None

    async def initialize(self, echo: bool = False) -> None:
        """Initialize the database engine and session factory."""
        if self._engine is not None:
            logging.warning("Session manager already initialized")
            return

        try:
            self._engine = create_async_engine(
                db_config.database_url,
                echo=echo,
                poolclass=AsyncAdaptedQueuePool,
                pool_size=2,
                max_overflow=8,
                pool_timeout=30.0,
                pool_pre_ping=True,
            )

            self._sessionmaker = async_sessionmaker(
                self._engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
                autocommit=False,
            )

            async with self._engine.begin() as conn:
                await conn.execute(text("SELECT 1"))

            logging.info("Session manager initialized successfully")

        except Exception as e:
            logging.error(f"Failed to initialize session manager: {e}")
            raise ExceptionHandler(
                message=f"Failed to initialize database: {str(e)}",
                error_code=500,
            )

    async def close(self) -> None:
        """Close the database engine and cleanup resources."""
        if self._engine is None:
            return

        await self._engine.dispose()
        self._engine = None
        self._sessionmaker = None
        logging.info("Session manager closed")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session."""
        if self._sessionmaker is None:
            raise ExceptionHandler(
                message="Sesion manager not initialized",
                error_code=500,
            )

        async with self._sessionmaker() as session:
            try:
                yield session
            except Exception as e:
                await session.rollback()
                logging.error(f"Session error: {e}")
                raise ExceptionHandler(
                    message=f"Session error {str(e)}", error_code=500
                )
            finally:
                await session.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session with automatic transaction handling."""
        async with self.session() as session:
            async with session.begin():
                yield session

    async def health_check(self) -> dict:
        """Check database health and connection pool status."""
        if self._engine is None:
            return {"status": "error", "message": "Database not initialized"}

        try:
            async with self._engine.connect() as conn:
                result = await conn.execute(text("SELECT version()"))
                version = result.scalar()

            pool = self._engine.pool

            return {
                "status": "healthy",
                "database_version": version,
                "pool_size": pool.size() if hasattr(pool, "size") else "N/A",
                "checked_out_connections": (
                    pool.checkedout() if hasattr(pool, "checkedout") else "N/A"
                ),
            }
        except Exception as e:
            logging.error(f"Health check failed: {e}")
            return {"status": "error", "message": str(e)}

    @property
    def engine(self) -> AsyncEngine:
        """Get the database engine."""
        if self._engine is None:
            raise ExceptionHandler(
                message="Session manager not initialized",
                error_code=500,
            )
        return self._engine


session_manager = SessionManager()
