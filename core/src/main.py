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
    logs,
    authorization,
    admin,
    sessions,
    mapping,
)
from src.infrastructure.database import db
from src.infrastructure.filesystem import configure_git_credentials
from src.infrastructure.templates.prompt_seeder import build_default_seeder
from src.shared.config.system_config import system_config
from src.shared.logger import logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup and shutdown events."""
    # Startup
    logging.info("Starting Nebula application...")
    try:
        await db.initialize()
        logging.info("Database initialized successfully")
    except Exception as e:
        logging.error(f"Failed to initialize database: {e}")
        raise

    # Seed Phoenix with example prompts so a fresh deployment is runnable
    # end-to-end. Only the prompts missing from Phoenix are created;
    # user-curated prompts are left alone. Boot fails if seeding fails.
    try:
        await build_default_seeder().ensure_seeded()
    except Exception as e:
        logging.error(f"Failed to seed prompts into Phoenix: {e}")
        raise

    try:
        _ = configure_git_credentials()
    except Exception as e:
        logging.warning(f"Failed to configure git credentials: {e}")

    yield

    # Shutdown
    logging.info("Shutting down Nebula application...")
    await db.close()
    logging.info("Database connection closed")


app = FastAPI(
    title="Nebula",
    description="Generate compliant Infrastructure as Code with a couple of clicks",
    version=os.getenv("APP_VERSION", "0.0.0-dev"),
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
app.include_router(logs.router, prefix="/v1")
app.include_router(authorization.router, prefix="/v1")
app.include_router(admin.router, prefix="/v1")
app.include_router(sessions.router, prefix="/v1")
app.include_router(mapping.router, prefix="/v1")

