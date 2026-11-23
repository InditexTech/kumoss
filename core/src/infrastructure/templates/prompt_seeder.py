# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Bootstraps Langfuse with the example prompts needed for Kumoss's IaC flows.

Runs at application startup. A missing prompt is created. The version the
seeder last pushed carries the `seed` label; when its text differs from the
seed on disk, the seeder pushes the seed again and moves the environment
labels still on that version, so a seed improved in a release reaches
upgraded installs while an environment label an operator points at their
own version is never moved.

Langfuse creates a version together with its labels and moves several
labels in one request, so each push either lands whole or not at all.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import get_args

import httpx

from src.infrastructure.exceptions import PromptSeedPushError
from src.infrastructure.templates._langfuse_prompts import (
    LATEST,
    LangfusePrompts,
    PromptVersion,
    default_client,
)
from src.infrastructure.templates._seed_loader import SeedEntry, SeedLoader
from src.shared.constants import Environment
from src.shared.logger import logging

# Answers worth waiting out while Langfuse boots: it runs its database
# migrations before it serves, and a proxy in front answers 502/503 until then.
_RETRYABLE_STATUS: frozenset[int] = frozenset({502, 503, 504})


class PromptSeeder:
    # About a minute and a half: a cold Langfuse migrates Postgres and
    # ClickHouse before it answers.
    _CONNECT_BACKOFF: tuple[float, ...] = (
        0.5,
        1.0,
        2.0,
        4.0,
        5.0,
        5.0,
        5.0,
        5.0,
        5.0,
        5.0,
        10.0,
        10.0,
        10.0,
        10.0,
        10.0,
    )

    # Every environment, so changing `environment` later still finds the
    # seeded prompts without labelling them by hand in Langfuse.
    _LABELS: tuple[Environment, ...] = get_args(Environment)

    # On the version the seeder last pushed for each prompt.
    _SEED_LABEL: str = "seed"

    def __init__(self, seed_dir: Path, prompts: LangfusePrompts):
        self._loader: SeedLoader = SeedLoader(seed_dir)
        self._prompts: LangfusePrompts = prompts

    async def ensure_seeded(self) -> None:
        """Load YAML seeds, create the ones missing from Langfuse and update
        the ones whose `seed` version differs from disk.

        Raises:
            PromptSeedLoadError: a seed file is malformed or the seed dir is missing.
            PromptSeedPushError: Langfuse is unreachable after retries, refuses
                the key pair, or a write fails.
        """
        entries = self._loader.load()
        logging.info(
            f"Prompt seeder loaded {len(entries)} entries from disk "
            + f"(labels={', '.join(self._LABELS)})"
        )

        await self._probe()

        created = 0
        updated = 0
        unchanged = 0
        for entry in entries:
            seed = await self._seed_version(entry)
            if seed is None:
                await self._create(entry, (*self._LABELS, self._SEED_LABEL))
                created += 1
            elif seed.text != entry.body:
                owned = tuple(label for label in self._LABELS if label in seed.labels)
                labels = (*owned, self._SEED_LABEL)
                current = await self._current_version(entry, seed)
                if current is None:
                    # Same type as the prompt: Langfuse refuses a change.
                    await self._create(entry, labels, chat_role=seed.chat_role)
                else:
                    await self._label(entry, current, labels)
                updated += 1
            else:
                unchanged += 1

        logging.info(
            f"Prompt seeding complete: {created} created, {updated} updated, "
            + f"{unchanged} unchanged"
        )

    async def _probe(self) -> None:
        """Make one authenticated read, retrying while Langfuse is not
        answering yet.

        Compose's `depends_on` and Kubernetes don't wait for readiness, so
        a cold boot can hit ConnectionRefused for a while. Any other failure
        is immediate — a refused key pair (401) is a configuration error,
        not a not-yet-listening server.
        """
        last_err: Exception | None = None
        for attempt, delay in enumerate(self._CONNECT_BACKOFF, start=1):
            try:
                await self._prompts.check_access()
                return
            except httpx.HTTPStatusError as e:
                if e.response.status_code not in _RETRYABLE_STATUS:
                    raise PromptSeedPushError(
                        message=_refusal(e),
                        error_code=502,
                    ) from e
                last_err = e
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                last_err = e
            except httpx.HTTPError as e:
                raise PromptSeedPushError(
                    message=f"Langfuse probe failed: {e}",
                    error_code=502,
                ) from e
            logging.info(
                f"Langfuse not ready yet (attempt {attempt}/{len(self._CONNECT_BACKOFF)}): {last_err}"
            )
            await asyncio.sleep(delay)

        raise PromptSeedPushError(
            message=f"Langfuse unreachable after {len(self._CONNECT_BACKOFF)} attempts: {last_err}",
            error_code=504,
        )

    async def _get(self, entry: SeedEntry, label: str) -> PromptVersion | None:
        try:
            return await self._prompts.get(entry.qualified_name, label=label)
        except httpx.HTTPError as e:
            raise PromptSeedPushError(
                message=f"Error reading '{entry.qualified_name}' labelled '{label}': {e}",
                error_code=502,
            ) from e

    async def _seed_version(self, entry: SeedEntry) -> PromptVersion | None:
        """The version labelled `seed`, or None when the prompt is missing.

        A prompt without the label was seeded before it existed or had it
        removed: its latest version is taken as the seeder's and labelled.
        """
        seed = await self._get(entry, self._SEED_LABEL)
        if seed is not None:
            return seed
        latest = await self._get(entry, LATEST)
        if latest is None:
            return None
        await self._label(entry, latest, (self._SEED_LABEL,))
        logging.info(
            f"Labelled the latest version of {entry.qualified_name} as "
            + f"'{self._SEED_LABEL}'"
        )
        return latest

    async def _current_version(
        self, entry: SeedEntry, seed: PromptVersion
    ) -> PromptVersion | None:
        """The latest version when it already holds the text on disk.

        It does when an operator, or a migration from another prompt store,
        saved the new seed text before this boot: the labels join it rather
        than getting another copy.
        """
        latest = await self._get(entry, LATEST)
        if (
            latest is not None
            and latest.version != seed.version
            and latest.text == entry.body
        ):
            return latest
        return None

    async def _create(
        self,
        entry: SeedEntry,
        labels: tuple[str, ...],
        chat_role: str | None = None,
    ) -> None:
        try:
            created = await self._prompts.create(
                entry.qualified_name,
                entry.body,
                labels=labels,
                commit_message=entry.description,
                chat_role=chat_role,
            )
        except httpx.HTTPError as e:
            raise PromptSeedPushError(
                message=f"Failed to create prompt '{entry.qualified_name}': {e}",
                error_code=502,
            ) from e
        logging.info(
            f"Pushed prompt: {entry.qualified_name} v{created.version} "
            + f"(labels={', '.join(labels)})"
        )

    async def _label(
        self, entry: SeedEntry, version: PromptVersion, labels: tuple[str, ...]
    ) -> None:
        try:
            await self._prompts.set_labels(
                entry.qualified_name, version.version, labels
            )
        except httpx.HTTPError as e:
            raise PromptSeedPushError(
                message=(
                    f"Failed to label '{entry.qualified_name}' version "
                    + f"{version.version} with {', '.join(labels)}: {e}"
                ),
                error_code=502,
            ) from e
        logging.info(
            f"Labelled {entry.qualified_name} v{version.version} "
            + f"(labels={', '.join(labels)})"
        )


def _refusal(e: httpx.HTTPStatusError) -> str:
    if e.response.status_code in (401, 403):
        return (
            f"Langfuse refused the API key pair ({e.response.status_code}): set "
            + "the env vars named by telemetry.public_key_env and "
            + "telemetry.secret_key_env to a key pair of the Langfuse project."
        )
    return f"Langfuse probe failed: {e}"


def build_default_seeder() -> PromptSeeder:
    """Factory for the application-default seeder.

    Resolves the seed directory relative to this file so the path is stable
    regardless of the process's current working directory.
    """
    seed_dir = Path(__file__).resolve().parents[3] / "prompts" / "seed"
    return PromptSeeder(seed_dir=seed_dir, prompts=default_client())
