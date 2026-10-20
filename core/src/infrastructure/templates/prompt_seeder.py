# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Bootstraps Phoenix with the example prompts needed for Kumoss's IaC flows.

Runs at application startup. A missing prompt is created. An existing one is
brought up to date only for the environment tags that still point at a version
the seeder itself pushed, so a seed improved in a release reaches upgraded
installs while user-curated prompts are never overwritten: once an operator
saves their own version under a tag, the seeder leaves that tag alone.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, get_args

import httpx
from phoenix.client import AsyncClient
from phoenix.client.types.prompts import PromptVersion

from src.infrastructure.exceptions import PromptSeedPushError
from src.infrastructure.templates._released_seed_digests import (
    RELEASED_SEED_DIGESTS,
)
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

    # Appended to the description of every version the seeder pushes. The
    # digest is of the version's own text, so a user who saves an edited copy
    # (description included) produces a version whose marker no longer matches.
    _DIGEST_MARKER: re.Pattern[str] = re.compile(
        r"\[kumoss-seed sha256:([0-9a-f]{64})\]"
    )

    def __init__(self, seed_dir: Path, phoenix_base_url: str):
        self._loader = SeedLoader(seed_dir)
        self._client = AsyncClient(base_url=phoenix_base_url)

    async def ensure_seeded(self) -> None:
        """Load YAML seeds, create the ones missing from Phoenix and update
        the ones still on a seeder-pushed version that differs from disk.

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
        skipped = 0
        for entry in entries:
            if not await self._exists(entry.qualified_name):
                await self._push(entry, self._TAGS)
                created += 1
                continue
            stale, current_id = await self._stale_tags(entry)
            if stale:
                await self._push(entry, stale, version_id=current_id)
                updated += 1
            else:
                skipped += 1

        logging.info(
            f"Prompt seeding complete: {created} created, {updated} updated, "
            + f"{skipped} unchanged or curated"
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

    async def _stale_tags(
        self, entry: SeedEntry
    ) -> tuple[tuple[Environment, ...], str | None]:
        """The environment tags whose version the seeder pushed and whose text
        differs from the seed on disk, and the id of a seeder-pushed version
        another tag already holds with the text on disk, if any.

        A tag on a version the seeder did not push, or a tag an operator
        removed, is left alone. The current version is there when an earlier
        boot moved only some tags before failing: the rest join it rather
        than getting another copy of the same text.
        """
        stale: list[Environment] = []
        current_id: str | None = None
        for tag in self._TAGS:
            try:
                version = await self._client.prompts.get(
                    prompt_identifier=entry.qualified_name, tag=tag
                )
            except ValueError:
                continue  # tag removed by an operator
            except httpx.HTTPError as e:
                raise PromptSeedPushError(
                    message=(
                        f"Error reading '{entry.qualified_name}' tagged '{tag}': {e}"
                    ),
                    error_code=502,
                ) from e
            data = self._data(version)
            text = self._text(data)
            if text is None or not self._seeder_pushed(data, text):
                continue
            if text != entry.body:
                stale.append(tag)
            elif current_id is None:
                current_id = version.id
        return tuple(stale), current_id

    @staticmethod
    def _data(version: PromptVersion) -> Mapping[str, Any]:
        """The version as Phoenix's REST API spells it.

        The client exposes a version's content only through private names;
        ``_dumps`` is the one it sends to Phoenix itself, so its keys follow
        the API schema rather than the client's internals.
        """
        return version._dumps()  # pyright: ignore[reportPrivateUsage]

    @classmethod
    def _seeder_pushed(cls, data: Mapping[str, Any], text: str) -> bool:
        digest = _digest(text)
        marker = cls._DIGEST_MARKER.search(data.get("description") or "")
        if marker is not None:
            return marker.group(1) == digest
        return digest in RELEASED_SEED_DIGESTS

    @staticmethod
    def _text(data: Mapping[str, Any]) -> str | None:
        """The single text message the seeder writes, or None for any other
        shape, which only a user could have saved."""
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
        tags: tuple[Environment, ...],
        version_id: str | None = None,
    ) -> None:
        """Tag ``tags`` onto ``version_id``, or onto a new version of the seed
        when there is none to reuse."""
        if version_id is None:
            version_id = await self._create(entry)

        # A failure leaves the remaining tags for the operator to add by hand:
        # a new prompt's untagged environments look operator-removed to the
        # next boot, which therefore never tags them itself.
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

        logging.info(
            f"Pushed prompt: {entry.qualified_name} (tags={', '.join(tags)})"
        )

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
            description=(
                f"{entry.description or ''} [kumoss-seed sha256:{_digest(entry.body)}]"
            ).strip(),
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


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
