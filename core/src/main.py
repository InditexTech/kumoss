# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.v1 import (
    terraform,
    events,
    repository,
    auth,
    admin,
    session,
    mapping,
    users,
    notifications,
)
from src.scheduler.api import operations_router, schedules_router
from src.infrastructure.database import db
from src.infrastructure.redis import redis_client
from src.infrastructure.filesystem import configure_git_credentials
from src.infrastructure.storage import default_object_storage, terraform_state_storage
from src.infrastructure.telemetry._initializer import shutdown_tracer_providers
from src.infrastructure.templates.prompt_seeder import build_default_seeder
from src.scheduler.config import SchedulerConfig
from src.scheduler.executor import OperationExecutor
from src.scheduler.queue_service import OperationQueueService
from src.scheduler.scheduler import OperationScheduler
from src.shared.config.system_config import system_config
from src.shared.logger import logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup and shutdown events."""
    # Startup
    logging.info("Starting Nebula application...")
    try:
        await db.initialize(echo=False)
        logging.info("Database initialized successfully")
    except Exception as e:
        logging.error(f"Failed to initialize database: {e}")
        raise

    try:
        await redis_client.initialize()
        logging.info("Redis initialized successfully")
    except Exception as e:
        logging.error(f"Failed to initialize redis: {e}")
        raise

    try:
        await default_object_storage().ensure_bucket()
        state_storage = terraform_state_storage()
        if state_storage is not None:
            await state_storage.ensure_bucket()
        logging.info("Object storage initialized successfully")
    except Exception as e:
        logging.error(f"Failed to initialize object storage: {e}")
        raise

    try:
        await build_default_seeder().ensure_seeded()
    except Exception as e:
        logging.error(f"Failed to seed prompts into Phoenix: {e}")
        raise

    try:
        _ = configure_git_credentials()
    except Exception as e:
        logging.warning(f"Failed to configure git credentials: {e}")

    scheduler_config = system_config.scheduler
    scheduler: OperationScheduler | None = None
    if scheduler_config.enabled:
        queue = OperationQueueService(scheduler_config)
        executor = OperationExecutor(queue, scheduler_config)
        scheduler = OperationScheduler(queue, executor, scheduler_config)
        await scheduler.start()
        logging.info("Operation scheduler started")
    else:
        logging.info("Operation scheduler disabled (scheduler.enabled=false)")

    yield

    if scheduler is not None:
        await scheduler.stop()
        logging.info("Operation scheduler stopped")

    # Shutdown
    logging.info("Shutting down Nebula application...")
    shutdown_tracer_providers()
    logging.info("Tracer providers flushed and shut down")
    await redis_client.close()
    logging.info("Redis connection closed")
    await db.close()
    logging.info("Database connection closed")


tags_metadata: list[dict[str, str]] = [
    {
        "name": "Infrastructure as Code",
        "description": "Session-creating IaC operations (generate, drift, apply).",
    },
    {
        "name": "Events Subscription",
        "description": "Server-sent events for session progress.",
    },
    {
        "name": "Repository Operations",
        "description": "Git repository and pull-request operations.",
    },
    {
        "name": "Session Management",
        "description": "Session read models (list and detail).",
    },
    {
        "name": "Mapping",
        "description": "Passthrough to the mapping service.",
    },
    {
        "name": "Authentication",
        "description": "Public auth configuration for the SPA login flow and "
        "authorization decisions for cloud projects.",
    },
    {
        "name": "Users",
        "description": "The authenticated caller's identity and roles.",
    },
    {
        "name": "Admin",
        "description": "Admin panel: cross-user sessions, locks, and role management.",
    },
    {
        "name": "Notifications",
        "description": "User-originated notifications relayed to the notifications service.",
    },
]

app = FastAPI(
    title="Nebula",
    summary="Browser-facing orchestration API of the Nebula core engine.",
    description="Generate compliant Infrastructure as Code with a couple of clicks",
    version=os.getenv("APP_VERSION", "0.0.0-dev"),
    contact={
        "name": "Nebula maintainers",
        "url": "https://github.com/InditexTech/nebula",
    },
    license_info={
        "name": "Apache-2.0",
        "url": "https://github.com/InditexTech/nebula/blob/main/LICENSE",
    },
    openapi_tags=tags_metadata,
    swagger_ui_parameters={"syntaxHighlight.theme": "nord"},
    root_path="/api",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=system_config.http.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

### V1 ###
app.include_router(terraform.router, prefix="/v1")
app.include_router(events.router, prefix="/v1")
app.include_router(repository.router, prefix="/v1")
app.include_router(auth.router, prefix="/v1")
app.include_router(admin.router, prefix="/v1")
app.include_router(session.router, prefix="/v1")
app.include_router(mapping.router, prefix="/v1")
app.include_router(users.router, prefix="/v1")
app.include_router(notifications.router, prefix="/v1")
app.include_router(schedules_router, prefix="/v1")
app.include_router(operations_router, prefix="/v1")
