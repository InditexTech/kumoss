# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""``CloudCli``: the one object ``main`` talks to for every cloud concern.

Owns the provider instances, the login timestamp and its lock, and the
policy that spans providers (credential validation, independent login
attempts with retry, scope env merging, resource-id listing).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

from .. import engine
from ..config import Config
from ..engine import CommandResult
from ..models import CredentialError, LoginError, MissingCredentialError
from ._aws import AwsProvider
from ._azure import AzureProvider
from ._base import CloudProvider, _failure, _ids_result
from ._gcp import GcpProvider

logger = logging.getLogger(__name__)

PROVIDERS: tuple[type[CloudProvider], ...] = (AzureProvider, GcpProvider, AwsProvider)


class CloudCli:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._providers: list[CloudProvider] = [cls(config) for cls in PROVIDERS]
        self._by_name = {p.name: p for p in self._providers}
        self._last_login = 0.0
        self._login_lock = asyncio.Lock()

    # -- readiness ----------------------------------------------------------

    def validate_credentials(self) -> None:
        """Raise ``MissingCredentialError`` if any provider is only partially
        configured. Zero configured providers passes; every provider's gaps
        are reported at once so the deployment is fixed in one pass."""
        missing = {
            p.display_name: p.missing_env()
            for p in self._providers
            if p.is_configured() and not p.is_ready()
        }
        if missing:
            raise MissingCredentialError(missing)

    def ready_providers(self) -> list[CloudProvider]:
        """Providers with complete credentials; the rest are logged once."""
        ready: list[CloudProvider] = []
        for provider in self._providers:
            if provider.is_ready():
                ready.append(provider)
            else:
                logger.info(
                    "%s skipped: %s not set",
                    provider.display_name,
                    ", ".join(provider.missing_env()),
                )
        return ready

    def cli_available(self, provider: str) -> bool:
        found = self._by_name.get(provider)
        return found is not None and found.cli_available()

    def cli_binary(self, provider: str) -> str:
        """Binary a provider shells out to; unknown names echo back so
        error messages still say something useful."""
        found = self._by_name.get(provider)
        return provider if found is None else found.cli_binary

    # -- login --------------------------------------------------------------

    def needs_relogin(self) -> bool:
        if self._last_login == 0.0:
            return True
        elapsed = time.monotonic() - self._last_login
        return elapsed > self._config.cloud_login_refresh_min * 60

    async def _attempt_logins(self, providers: list[CloudProvider]) -> dict[str, str]:
        """Log into every provider independently; return the failures."""
        errors: dict[str, str] = {}
        for provider in providers:
            try:
                await provider.login()
            except LoginError as exc:
                detail = "; ".join(exc.failures.values())
                logger.error("%s login failed: %s", provider.display_name, detail)
                errors[provider.display_name] = detail
            else:
                logger.info("%s login successful", provider.display_name)
        return errors

    async def login(self, *, retries: int = 0) -> None:
        """Authenticate against every ready provider.

        Double-check locking: the first caller to find the token expired
        acquires the lock and re-authenticates; concurrent callers re-check
        inside the lock and skip if another task already refreshed.

        Providers that fail are retried up to *retries* more times with
        exponential backoff (``cloud_login_retry_delay_sec * 2**n``),
        re-attempting only the ones that failed. If any still fail, a
        single ``LoginError`` naming all of them is raised and
        ``_last_login`` is left untouched so the next caller tries again.

        Startup calls this with ``retries=0`` (fail fast on broken
        credentials); ``ensure_login`` uses ``config.cloud_login_retries``
        because a refresh failure is usually transient.
        """
        async with self._login_lock:
            if not self.needs_relogin():
                logger.debug("cloud tokens still valid, skipping re-login")
                return

            pending = self.ready_providers()
            errors = await self._attempt_logins(pending)

            for attempt in range(1, retries + 1):
                if not errors:
                    break
                delay = self._config.cloud_login_retry_delay_sec * 2 ** (attempt - 1)
                logger.warning(
                    "cloud login retry %d/%d for %s in %.1fs",
                    attempt,
                    retries,
                    ", ".join(errors),
                    delay,
                )
                await asyncio.sleep(delay)
                errors = await self._attempt_logins(
                    [p for p in pending if p.display_name in errors]
                )

            if errors:
                raise LoginError(errors)

            self._last_login = time.monotonic()
            logger.info("cloud login completed")

    async def ensure_login(self) -> None:
        """Lazy refresh for jobs that shell out to a cloud CLI; no-op while
        tokens are fresh. Engine commands do not need this: the Terraform
        providers and backends authenticate from the env vars ``scope_env``
        injects, never from the CLI session."""
        if self.needs_relogin():
            await self.login(retries=self._config.cloud_login_retries)

    # -- per-job environment ------------------------------------------------

    async def scope_env(self, scope_id: str) -> dict[str, str]:
        """Process env plus every ready provider's scope injection.

        Raises ``CredentialError`` (a 422 for the job) when no provider is
        ready, listing each provider's missing vars.

        A provider's injection may fail (today only AWS AssumeRole raises:
        ``RuntimeError`` when STS refuses, ``OSError`` when the CLI is
        missing). Cross-cloud plans are not supported, so when *another*
        provider is ready the ``scope_id`` most likely belongs to it and
        the failure is expected: it is logged at debug and skipped. When
        the failing provider is the *only* ready one, the scope can only be
        its own and the error propagates (job fails 500). Swallowing it
        there would run the engine on the service's static credentials,
        i.e. against whatever account those belong to.
        """
        ready = [p for p in self._providers if p.is_ready()]
        if not ready:
            raise CredentialError(
                {p.display_name.lower(): p.missing_env() for p in self._providers}
            )
        env = dict(os.environ)
        for provider in ready:
            try:
                env.update(await provider.scope_env(scope_id))
            except (RuntimeError, OSError) as exc:
                if len(ready) == 1:
                    raise
                logger.debug(
                    "%s scope injection skipped for scope %s: %s",
                    provider.display_name,
                    scope_id,
                    exc,
                )
        return env

    # -- resource-id listing ------------------------------------------------

    async def state_resource_ids(
        self, binary: str, workspace: Path, env: dict[str, str]
    ) -> CommandResult:
        """Managed resource ids from the workspace's state as a JSON array."""
        result = await engine.state_pull(binary, workspace, env=env)
        if not result.ok:
            return _failure(result.stderr, result.exit_code)
        return _ids_result(engine.extract_managed_resource_ids(result.stdout))

    async def scope_resource_ids(self, provider: str, scope_id: str) -> CommandResult:
        """Resource ids in one cloud scope as a JSON array on stdout."""
        found = self._by_name.get(provider)
        if found is None:
            return _failure(
                f"Unsupported terraform_provider: {provider!r}", exit_code=2
            )
        return await found.list_resource_ids(scope_id)
