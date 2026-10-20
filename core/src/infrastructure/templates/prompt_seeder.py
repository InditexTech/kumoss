# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Bootstraps Phoenix with the example prompts needed for Kumoss's IaC flows.

Runs at application startup. A missing prompt is created. The version the
seeder last pushed carries the `seed` tag; when its text differs from the seed
on disk, the seeder pushes the seed again and moves the environment tags still
on that version, so a seed improved in a release reaches upgraded installs
while an environment tag an operator points at their own version is never
moved.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any, get_args

import httpx
from phoenix.client import AsyncClient
from phoenix.client.types.prompts import PromptVersion

from src.infrastructure.exceptions import PromptSeedPushError
from src.infrastructure.templates._seed_loader import SeedEntry, SeedLoader
from src.shared.config import system_config
from src.shared.constants import Environment
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

    _SEED_MODEL_NAME: str = "kumoss-seed"

    # Every environment, so changing `environment` later still finds the
    # seeded prompts without re-tagging them by hand in Phoenix.
    _TAGS: tuple[Environment, ...] = get_args(Environment)

    # On the version the seeder last pushed for each prompt.
    _SEED_TAG: str = "seed"

    def __init__(self, seed_dir: Path, phoenix_base_url: str):
        self._loader = SeedLoader(seed_dir)
        self._client = AsyncClient(base_url=phoenix_base_url)

    async def ensure_seeded(self) -> None:
        """Load YAML seeds, create the ones missing from Phoenix and update
        the ones whose `seed` version differs from disk.

        Raises:
            PromptSeedLoadError: a seed file is malformed or the seed dir is missing.
            PromptSeedPushError: Phoenix is unreachable after retries, or a write
                fails with a non-connection error.
        """
        entries = self._loader.load()
        logging.info(
            f"Prompt seeder loaded {len(entries)} entries from disk "
            + f"(tags={', '.join(self._TAGS)})"
        )

        await self._probe_phoenix()

        created = 0
        updated = 0
        unchanged = 0
        for entry in entries:
            seed = await self._seed_version(entry)
            if seed is None:
                await self._push(entry, (*self._TAGS, self._SEED_TAG))
                created += 1
            elif self._text(self._data(seed)) != entry.body:
                owned, current_id = await self._owned_tags(entry, seed)
                await self._push(entry, (*owned, self._SEED_TAG), version_id=current_id)
                updated += 1
            else:
                unchanged += 1

        logging.info(
            f"Prompt seeding complete: {created} created, {updated} updated, "
            + f"{unchanged} unchanged"
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
        probe_name = "kumoss_seed_probe_does_not_exist"
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

    async def _get(
        self, entry: SeedEntry, tag: str | None = None
    ) -> PromptVersion | None:
        """The version ``tag`` points at, or the latest one without a tag;
        None when there is none."""
        try:
            return await self._client.prompts.get(
                prompt_identifier=entry.qualified_name, tag=tag
            )
        except ValueError:
            # Phoenix client wraps 404 as ValueError("Prompt not found: ...").
            return None
        except httpx.HTTPError as e:
            raise PromptSeedPushError(
                message=(
                    f"Error reading '{entry.qualified_name}'"
                    + (f" tagged '{tag}'" if tag else "")
                    + f": {e}"
                ),
                error_code=502,
            ) from e

    async def _seed_version(self, entry: SeedEntry) -> PromptVersion | None:
        """The version tagged `seed`, or None when the prompt is missing.

        A prompt without the tag was seeded before it existed or had it
        removed: its latest version is taken as the seeder's and tagged.
        """
        seed = await self._get(entry, self._SEED_TAG)
        if seed is not None:
            return seed
        latest = await self._get(entry)
        if latest is None:
            return None
        await self._tag(entry, latest.id, (self._SEED_TAG,))
        logging.info(
            f"Tagged the latest version of {entry.qualified_name} as "
            + f"'{self._SEED_TAG}'"
        )
        return latest

    async def _owned_tags(
        self, entry: SeedEntry, seed: PromptVersion
    ) -> tuple[tuple[Environment, ...], str | None]:
        """The environment tags still on the `seed` version, and the id of
        the latest version when it already holds the text on disk.

        A tag on any other version, or a tag an operator removed, is left
        alone. The latest version holds the text on disk when an earlier
        boot pushed it and failed before moving `seed`, which only moves
        last: the remaining tags join it rather than getting another copy.
        """
        owned: list[Environment] = []
        for tag in self._TAGS:
            version = await self._get(entry, tag)
            if version is not None and version.id == seed.id:
                owned.append(tag)
        latest = await self._get(entry)
        current_id = None
        if (
            latest is not None
            and latest.id != seed.id
            and self._text(self._data(latest)) == entry.body
        ):
            current_id = latest.id
        return tuple(owned), current_id

    @staticmethod
    def _data(version: PromptVersion) -> Mapping[str, Any]:
        """The version as Phoenix's REST API spells it.

        The client exposes a version's content only through private names;
        ``_dumps`` is the one it sends to Phoenix itself, so its keys follow
        the API schema rather than the client's internals.
        """
        return version._dumps()  # pyright: ignore[reportPrivateUsage]

    @staticmethod
    def _text(data: Mapping[str, Any]) -> str | None:
        """The single text message the seeder writes, or None for any other
        shape, which therefore never matches a seed."""
        try:
            messages = data["template"]["messages"]
            if len(messages) != 1:
                return None
            content = messages[0]["content"]
            if isinstance(content, str):
                return content
            if len(content) != 1 or content[0].get("type") != "text":
                return None
            text = content[0]["text"]
        except (KeyError, IndexError, TypeError, AttributeError):
            return None
        return text if isinstance(text, str) else None

    async def _push(
        self,
        entry: SeedEntry,
        tags: tuple[str, ...],
        version_id: str | None = None,
    ) -> None:
        """Tag ``tags`` onto ``version_id``, or onto a new version of the seed
        when there is none to reuse."""
        if version_id is None:
            version_id = await self._create(entry)
        await self._tag(entry, version_id, tags)
        logging.info(f"Pushed prompt: {entry.qualified_name} (tags={', '.join(tags)})")

    async def _tag(
        self, entry: SeedEntry, version_id: str, tags: tuple[str, ...]
    ) -> None:
        """Tag ``version_id`` in order, so `seed`, which callers pass last,
        moves only once every environment tag has."""
        # On a new prompt a failure leaves the remaining tags for the operator
        # to add by hand: the next boot tags the latest version `seed` and
        # leaves the untagged environments alone.
        for i, tag in enumerate(tags):
            try:
                await self._client.prompts.tags.create(
                    prompt_version_id=version_id,
                    name=tag,
                )
            except httpx.HTTPError as e:
                raise PromptSeedPushError(
                    message=(
                        f"Failed to tag '{entry.qualified_name}' "
                        f"(version {version_id}) with '{tag}': {e}. The version "
                        f"now exists; tag that version by hand with: {', '.join(tags[i:])}"
                    ),
                    error_code=502,
                ) from e

    async def _create(self, entry: SeedEntry) -> str:
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
        return version_id


def build_default_seeder() -> PromptSeeder:
    """Factory for the application-default seeder.

    Resolves the seed directory relative to this file so the path is stable
    regardless of the process's current working directory.
    """
    seed_dir = Path(__file__).resolve().parents[3] / "prompts" / "seed"
    return PromptSeeder(
        seed_dir=seed_dir,
        phoenix_base_url=system_config.telemetry.collector_url,
    )
