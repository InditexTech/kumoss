# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Bootstraps a fresh Phoenix instance with the example prompts needed for
Nebula's IaC flows. Runs at application startup and creates only the prompts
that don't already exist, so user-curated prompts are never overwritten.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from phoenix.client import AsyncClient
from phoenix.client.types.prompts import PromptVersion

from src.infrastructure.exceptions import PromptSeedPushError
from src.infrastructure.templates._seed_loader import SeedEntry, SeedLoader
from src.shared.config import system_config
from src.shared.logger import logging


class PromptSeeder:
    _CONNECT_BACKOFF: tuple[float, ...] = (
        0.5,
        1.0,
        2.0,
        4.0,
        5.0,
        5.0,
        5.0,
        5.0,
        7.0,
        10.0,
    )

    _SEED_MODEL_NAME: str = "nebula-seed"

    def __init__(self, seed_dir: Path, phoenix_base_url: str, tag: str):
        self._loader = SeedLoader(seed_dir)
        self._client = AsyncClient(base_url=phoenix_base_url)
        self._tag = tag

    async def ensure_seeded(self) -> None:
        """Load YAML seeds and push any that are missing from Phoenix.

        Raises:
            PromptSeedLoadError: a seed file is malformed or the seed dir is missing.
            PromptSeedPushError: Phoenix is unreachable after retries, or a write
                fails with a non-connection error.
        """
        entries = self._loader.load()
        logging.info(
            f"Prompt seeder loaded {len(entries)} entries from disk "
            + f"(env tag='{self._tag}')"
        )

        await self._probe_phoenix()

        created = 0
        skipped = 0
        for entry in entries:
            if await self._exists(entry.qualified_name):
                skipped += 1
                continue
            await self._push(entry)
            created += 1

        logging.info(
            f"Prompt seeding complete: {created} created, {skipped} already present"
        )

    async def _probe_phoenix(self) -> None:
        """Hit Phoenix once, retrying on connection-level failures only.

        Compose's `depends_on` doesn't wait for readiness, so a cold boot can
        hit ConnectionRefused for a few seconds. Non-connection errors fail
        immediately — they indicate a real problem, not a not-yet-listening one.

        The probe name must start with an alphanumeric character — Phoenix
        rejects names with leading underscores with 422, which would
        masquerade as a real failure here.
        """
        probe_name = "nebula_seed_probe_does_not_exist"
        last_err: Exception | None = None
        for attempt, delay in enumerate(self._CONNECT_BACKOFF, start=1):
            try:
                # Cheapest call: ask for a prompt that almost certainly doesn't
                # exist. 404 (ValueError) means Phoenix is up and answering.
                _ = await self._client.prompts.get(prompt_identifier=probe_name)
                return  # 200 — also fine
            except ValueError:
                return  # 404 from Phoenix == reachable
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                last_err = e
                logging.info(
                    f"Phoenix not ready yet (attempt {attempt}/{len(self._CONNECT_BACKOFF)}): {e}"
                )
                await asyncio.sleep(delay)
            except httpx.HTTPError as e:
                # Anything else is a real failure — surface it now.
                raise PromptSeedPushError(
                    message=f"Phoenix probe failed: {e}",
                    error_code=502,
                ) from e

        raise PromptSeedPushError(
            message=f"Phoenix unreachable after {len(self._CONNECT_BACKOFF)} attempts: {last_err}",
            error_code=504,
        )

    async def _exists(self, qualified_name: str) -> bool:
        try:
            _ = await self._client.prompts.get(prompt_identifier=qualified_name)
            return True
        except ValueError:
            # Phoenix client wraps 404 as ValueError("Prompt not found: ...").
            return False
        except httpx.HTTPError as e:
            raise PromptSeedPushError(
                message=f"Error checking existence of '{qualified_name}': {e}",
                error_code=502,
            ) from e

    async def _push(self, entry: SeedEntry) -> None:
        version = PromptVersion(
            [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": entry.body}],
                }
            ],
            model_name=self._SEED_MODEL_NAME,
            template_format="NONE",
            description=entry.description,
        )
        try:
            created = await self._client.prompts.create(
                version=version,
                name=entry.qualified_name,
                prompt_description=entry.description,
            )
        except httpx.HTTPError as e:
            raise PromptSeedPushError(
                message=f"Failed to create prompt '{entry.qualified_name}': {e}",
                error_code=502,
            ) from e

        version_id = created.id
        if not version_id:
            raise PromptSeedPushError(
                message=(
                    f"Phoenix returned no version id for '{entry.qualified_name}'; "
                    f"cannot tag"
                ),
                error_code=502,
            )

        try:
            await self._client.prompts.tags.create(
                prompt_version_id=version_id,
                name=self._tag,
            )
        except httpx.HTTPError as e:
            raise PromptSeedPushError(
                message=(
                    f"Failed to tag '{entry.qualified_name}' "
                    f"(version {version_id}) with '{self._tag}': {e}"
                ),
                error_code=502,
            ) from e

        logging.info(f"Created prompt: {entry.qualified_name}")


def build_default_seeder() -> PromptSeeder:
    """Factory for the application-default seeder.

    Resolves the seed directory relative to this file so the path is stable
    regardless of the process's current working directory.
    """
    seed_dir = Path(__file__).resolve().parents[3] / "prompts" / "seed"
    return PromptSeeder(
        seed_dir=seed_dir,
        phoenix_base_url=system_config.telemetry.collector_url,
        tag=system_config.environment,
    )
