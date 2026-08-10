# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic, reportAssignmentType=false, reportAttributeAccessIssue=false
import shutil
from contextvars import Token

from src.domains.services.tracer_service import TracerService
from src.infrastructure.telemetry.phoenix.phoenix_tracer import PhoenixTracer
from src.infrastructure.filesystem import GitUtils
from src.shared.constants import GitProviderName
from src.shared.logger import logging
from tests.settings import Settings

_TOKEN: Token = None


async def setup_repository(
    project_cloud: list[tuple[str, str]] | None = None, setup_tracer: bool = False
):
    if not project_cloud:
        project_cloud = [
            (Settings.DEFAULT_PROJECT_NAME, Settings.DEFAULT_PROJECT_CLOUD)
        ]
    for pair in project_cloud:
        # Test fixture: pair[0] is treated as the repo URL directly,
        # consistent with the OSS-default identity mapping behavior.
        if not await GitUtils(git_provider=GitProviderName.GITHUB).clone_repository(
            repo_url=pair[0],
            repository_name=f"{pair[0]}_{Settings.SESSION_ID}",
        ):
            logging.error(f"project {Settings.DEFAULT_PROJECT_NAME} couldn't be cloned")
            raise SystemExit()
    if setup_tracer:
        _setup_tracer()


def clean_resources(repositories: list[str] | None = None):
    try:
        if not repositories:
            repositories = [Settings.DEFAULT_PROJECT_UID]
        for repo_uid in repositories:
            shutil.rmtree(Settings.UPLOAD_DIR / repo_uid)
            logging.info(f"Deleted repository: {repo_uid}")

    except Exception as e:
        logging.error(f"Error deleting {Settings.DEFAULT_PROJECT_UID}: {e}")

    if _TOKEN:
        _teardown_tracer()


def _setup_tracer():
    global _TOKEN
    _TOKEN = TracerService.set_current_tracer(
        PhoenixTracer(
            session_id=Settings.SESSION_ID,
            user_id=Settings.USER_ID,
            cloud=Settings.TEMPLATE_PROVIDER,
            operation=Settings.DEFAULT_OPERATION,
            iac_path="/test",
            branch_name="test_branch",
        )
    )


def _teardown_tracer():
    global _TOKEN
    TracerService.reset_current_tracer(_TOKEN)
    _TOKEN = None
