# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Terraform Registry client used by the core's ``terraform_docs`` tool.

A resource page is two calls away. ``/v1/providers/<ns>/<name>[/<version>]``
pins the provider version (the bare provider answers with its latest one
and the full list of published versions) and lists every documentation
page of that version with its registry id; ``/v2/provider-docs/<id>`` then
returns the page, already as markdown. The page index of an aws release
is over a megabyte, so the index of every version read is kept
in-process: the import agent asks once per resource type, usually all
from one version.

Two failures are told apart, mirroring ``search_service``: a provider,
version or type the registry does not know raises
``TerraformDocsNotFoundError``, which the agent can fix by asking
differently, and an unreachable or misbehaving registry raises
``TerraformRegistryError``, which it cannot.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import Any, ClassVar

import httpx

from src.domains.value_objects import TerraformDoc
from src.infrastructure.exceptions import (
    TerraformDocsNotFoundError,
    TerraformRegistryError,
)


class TerraformRegistryClient:
    """Fetch one resource or data source page from the Terraform Registry."""

    REGISTRY_URL: ClassVar[str] = "https://registry.terraform.io"
    TIMEOUT: ClassVar[float] = 30.0
    # Cut before a page reaches the summarizer; aws_instance is ~50k.
    MAX_DOC_CHARS: ClassVar[int] = 60000

    __DEFAULT_HOST: ClassVar[str] = "registry.terraform.io"
    __DEFAULT_NAMESPACE: ClassVar[str] = "hashicorp"
    __INDEX_CACHE_SIZE: ClassVar[int] = 16
    __EXACT_VERSION: ClassVar[re.Pattern[str]] = re.compile(
        r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$"
    )
    __CONSTRAINT: ClassVar[re.Pattern[str]] = re.compile(
        r"^(~>|>=|<=|!=|=|>|<)?\s*v?(\d+(?:\.\d+){0,2})$"
    )
    __IMPORT_HEADING: ClassVar[re.Pattern[str]] = re.compile(
        r"^##\s+Import\b.*$", re.MULTILINE | re.IGNORECASE
    )
    __NEXT_SECTION: ClassVar[re.Pattern[str]] = re.compile(r"^##\s", re.MULTILINE)

    # (namespace, name, version) -> that version's documentation page index
    _doc_indexes: ClassVar[OrderedDict[tuple[str, str, str], list[dict[str, Any]]]] = (
        OrderedDict()
    )

    async def fetch(
        self,
        provider: str,
        resource_type: str,
        version: str | None = None,
        data_source: bool = False,
    ) -> TerraformDoc:
        """The page of ``resource_type`` in ``provider`` at ``version``.

        ``version`` is an exact version, a Terraform version constraint
        (``~> 5.0``, ``>= 4.2, < 6``) resolved to the newest published
        version satisfying it, or empty for the latest one.
        """
        namespace, name = self.split_source(provider)
        resource_type = resource_type.strip()
        async with httpx.AsyncClient(
            base_url=self.REGISTRY_URL,
            timeout=httpx.Timeout(self.TIMEOUT),
            follow_redirects=True,
        ) as client:
            exact, index = await self.__doc_index(client, namespace, name, version)
            category = "data-sources" if data_source else "resources"
            entry = self.__find_page(index, category, name, resource_type)
            if entry is None:
                raise TerraformDocsNotFoundError(
                    message=f"{namespace}/{name} {exact} documents no "
                    + f"{'data source' if data_source else 'resource'} "
                    + f"named '{resource_type}'.",
                    error_code=404,
                )
            page = await self.__get_json(client, f"/v2/provider-docs/{entry['id']}")
        try:
            content: str = page["data"]["attributes"]["content"]
        except (KeyError, TypeError) as e:
            raise TerraformRegistryError(
                message=f"the registry returned no content for {resource_type}",
                error_code=502,
            ) from e
        return TerraformDoc(
            source=f"{namespace}/{name}",
            version=exact,
            resource_type=resource_type,
            url=f"{self.REGISTRY_URL}/providers/{namespace}/{name}"
            + f"/{exact}/docs/{category}/{entry['slug']}",
            content=self.__strip_frontmatter(content),
        )

    @classmethod
    def import_section(cls, content: str) -> str | None:
        """The page's `## Import` section, heading included; ``None`` if it has none."""
        heading = cls.__IMPORT_HEADING.search(content)
        if heading is None:
            return None
        following = cls.__NEXT_SECTION.search(content, heading.end())
        end = following.start() if following else len(content)
        return content[heading.start() : end].strip()

    @classmethod
    def split_source(cls, provider: str) -> tuple[str, str]:
        """``<namespace>/<name>`` out of a provider source address.

        Takes the forms `required_providers` and the lock file use: a bare
        name (``aws``, meaning ``hashicorp/aws``), ``<ns>/<name>`` and
        ``registry.terraform.io/<ns>/<name>``.
        """
        parts = [p for p in provider.strip().lower().split("/") if p]
        if len(parts) == 3 and parts[0] == cls.__DEFAULT_HOST:
            parts = parts[1:]
        if len(parts) == 1:
            parts = [cls.__DEFAULT_NAMESPACE, parts[0]]
        if len(parts) != 2:
            raise TerraformDocsNotFoundError(
                message=f"'{provider}' is not a Terraform Registry provider source; "
                + "expected '<namespace>/<name>', e.g. 'hashicorp/aws'.",
                error_code=400,
            )
        return parts[0], parts[1]

    @classmethod
    def resolve_constraint(cls, constraint: str, versions: list[str]) -> str | None:
        """Newest release in ``versions`` satisfying a Terraform version constraint."""
        clauses: list[tuple[str, tuple[int, ...]]] = []
        for clause in constraint.split(","):
            match = cls.__CONSTRAINT.match(clause.strip())
            if match is None:
                return None
            bound = cls.__parse_version(match.group(2)) or ()
            clauses.append((match.group(1) or "=", bound))

        def satisfies(v: tuple[int, ...]) -> bool:
            for op, bound in clauses:
                padded = bound + (0,) * (3 - len(bound))
                if op == "~>":
                    # Only the rightmost given segment may grow.
                    prefix = bound[:-1] if len(bound) > 1 else bound
                    ok = v >= padded and v[: len(prefix)] == prefix
                else:
                    ok = {
                        "=": v == padded,
                        "!=": v != padded,
                        ">": v > padded,
                        ">=": v >= padded,
                        "<": v < padded,
                        "<=": v <= padded,
                    }[op]
                if not ok:
                    return False
            return True

        releases = [
            (p, v) for v in versions if (p := cls.__parse_version(v)) is not None
        ]
        matching = [(p, v) for p, v in releases if satisfies(p + (0,) * (3 - len(p)))]
        return max(matching)[1] if matching else None

    async def __doc_index(
        self,
        client: httpx.AsyncClient,
        namespace: str,
        name: str,
        version: str | None,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Pin ``version`` and return it with its page index."""
        version = (version or "").strip().removeprefix("v")
        if version.lower() == "latest":
            version = ""
        cache = TerraformRegistryClient._doc_indexes
        if version and self.__EXACT_VERSION.match(version):
            cached = cache.get((namespace, name, version))
            if cached is not None:
                cache.move_to_end((namespace, name, version))
                return version, cached
            body = await self.__get_json(
                client, f"/v1/providers/{namespace}/{name}/{version}"
            )
        else:
            body = await self.__get_json(client, f"/v1/providers/{namespace}/{name}")
            if version:
                resolved = self.resolve_constraint(version, body.get("versions") or [])
                if resolved is None:
                    raise TerraformDocsNotFoundError(
                        message=f"No published version of {namespace}/{name} "
                        + f"satisfies '{version}'.",
                        error_code=404,
                    )
                if resolved != body.get("version"):
                    return await self.__doc_index(client, namespace, name, resolved)
        exact = str(body.get("version") or version)
        index: list[dict[str, Any]] = body.get("docs") or []
        cache[(namespace, name, exact)] = index
        while len(cache) > self.__INDEX_CACHE_SIZE:
            _ = cache.popitem(last=False)
        return exact, index

    @staticmethod
    def __find_page(
        index: list[dict[str, Any]], category: str, name: str, resource_type: str
    ) -> dict[str, Any] | None:
        """The HCL page of ``resource_type``, whose slug drops the type prefix.

        The prefix is usually the provider name (``aws_s3_bucket`` is slug
        ``s3_bucket``), but not always (``google-beta`` documents
        ``google_*``), so the first underscore-separated word is tried next.
        """
        slugs = [
            resource_type.removeprefix(f"{name}_"),
            resource_type.split("_", 1)[-1],
            resource_type,
        ]
        pages = [
            p
            for p in index
            if p.get("category") == category and p.get("language", "hcl") == "hcl"
        ]
        for slug in slugs:
            for page in pages:
                if page.get("slug") == slug:
                    return page
        return None

    @staticmethod
    def __strip_frontmatter(content: str) -> str:
        if content.startswith("---"):
            end = content.find("\n---", 3)
            if end >= 0:
                return content[end + len("\n---") :].lstrip()
        return content

    @staticmethod
    def __parse_version(version: str) -> tuple[int, ...] | None:
        """Numeric release segments; ``None`` for a pre-release or a malformed version."""
        if not re.fullmatch(r"\d+(?:\.\d+)*", version):
            return None
        return tuple(int(p) for p in version.split("."))

    @staticmethod
    async def __get_json(client: httpx.AsyncClient, path: str) -> dict[str, Any]:
        try:
            response = await client.get(path)
        except httpx.TimeoutException as e:
            raise TerraformRegistryError(
                message="the Terraform Registry timed out", error_code=504
            ) from e
        except httpx.RequestError as e:
            raise TerraformRegistryError(
                message="the Terraform Registry is unreachable", error_code=502
            ) from e
        if response.status_code == 404:
            raise TerraformDocsNotFoundError(
                message="The Terraform Registry has no "
                + f"{path.removeprefix('/v1/providers/')}.",
                error_code=404,
            )
        if response.status_code != 200:
            raise TerraformRegistryError(
                message=f"the Terraform Registry answered HTTP {response.status_code}",
                error_code=502,
            )
        try:
            return response.json()
        except ValueError as e:
            raise TerraformRegistryError(
                message="the Terraform Registry returned invalid JSON", error_code=502
            ) from e
