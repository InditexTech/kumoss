# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Minimal database client with only essential operations."""

from typing import Any, TypeVar
from contextlib import asynccontextmanager

from sqlalchemy import ColumnExpressionArgument, select, func, desc, asc

from src.infrastructure.database.session import SessionManager, session_manager
from src.infrastructure.database.models import Base
from src.shared.logger import logging

T = TypeVar("T", bound=Base)


class DatabaseClient:
    """Async database client with SQLAlchemy ORM support."""

    def __init__(self):
        self.session_manager: SessionManager = session_manager
        self._initialized: bool = False

    async def initialize(self, echo: bool = False) -> None:
        """Initialize the database client."""
        if self._initialized:
            logging.warning("Database client already initialized")
            return

        await self.session_manager.initialize(echo=echo)

        await self._create_tables()

        self._initialized = True
        logging.info("Database client initialized")

    async def _create_tables(self) -> None:
        """Create all database tables if they don't exist."""
        try:
            async with self.session_manager.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logging.info("Database tables created/verified successfully")
        except Exception as e:
            logging.error(f"Error creating database tables: {e}")
            raise

    async def close(self) -> None:
        """Close the database client and cleanup resources."""
        await self.session_manager.close()
        self._initialized = False
        logging.info("Database client closed")

    @asynccontextmanager
    async def session(self):
        """Get a database session."""
        async with self.session_manager.session() as session:
            yield session

    @asynccontextmanager
    async def transaction(self):
        """Get a database session with transaction."""
        async with self.session_manager.transaction() as session:
            yield session

    async def get_by(self, model: type[T], **filters: Any) -> T | None:
        """Get a single record by filters."""
        async with self.session() as session:
            stmt = select(model)
            for key, value in filters.items():
                stmt = stmt.where(getattr(model, key) == value)

            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def create(self, model: type[T], **data: Any) -> T:
        """Create a new record."""
        async with self.transaction() as session:
            instance = model(**data)
            session.add(instance)
            await session.flush()
            await session.refresh(instance)
            return instance

    async def list_by(
        self,
        model: type[T],
        order_by: str | None = None,
        order_desc: bool = True,
        **filters: Any,
    ) -> list[T]:
        """Get all records matching filters."""
        async with self.session() as session:
            stmt = select(model)
            for key, value in filters.items():
                stmt = stmt.where(getattr(model, key) == value)
            if order_by and hasattr(model, order_by):
                col = getattr(model, order_by)
                stmt = stmt.order_by(desc(col) if order_desc else asc(col))
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def query(
        self,
        model: type[T],
        filters: dict[str, Any] | None = None,
        extra_conditions: list[ColumnExpressionArgument[Any]] | None = None,
        order_by: str = "created_at",
        order_desc: bool = True,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[T], int]:
        """Query records with filtering, ordering, and pagination.
        Returns (items, total_count).
        """
        async with self.session() as session:
            stmt = select(model)
            count_stmt = select(func.count()).select_from(model)

            if filters:
                for key, value in filters.items():
                    if value is not None and hasattr(model, key):
                        stmt = stmt.where(getattr(model, key) == value)
                        count_stmt = count_stmt.where(getattr(model, key) == value)

            if extra_conditions:
                for condition in extra_conditions:
                    stmt = stmt.where(condition)
                    count_stmt = count_stmt.where(condition)

            if hasattr(model, order_by):
                col = getattr(model, order_by)
                stmt = stmt.order_by(desc(col) if order_desc else asc(col))

            stmt = stmt.offset(offset).limit(limit)

            result = await session.execute(stmt)
            count_result = await session.execute(count_stmt)
            return list(result.scalars().all()), count_result.scalar_one()

    async def health_check(self) -> dict:
        """Check database health."""
        return await self.session_manager.health_check()


db = DatabaseClient()
