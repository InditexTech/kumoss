# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""HTTP request/response envelopes owned by the API layer."""

from datetime import datetime
from typing import Any, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from src.application.iac_requests import RepoUri
from src.domains.value_objects import ManifestResolution, ProviderRequirement
from src.shared.constants import OperationRole, PanelRole, TerraformProvider


class AuthConfigResponse(BaseModel):
    """Public OIDC settings the SPA needs to run its login flow.

    Blank ``issuer_url`` means auth is disabled (dev mode).
    """

    issuer_url: str
    client_id: str
    audience: str
    scope: str
    artifact_metadata_header_prefix: str


class UserMeResponse(BaseModel):
    """The caller's identity and roles, as the SPA consumes them."""

    id: int
    email: str | None
    display_name: str | None
    operation_role: OperationRole
    panel_role: PanelRole | None


class AdminUserEntry(UserMeResponse):
    issuer: str
    subject: str
    created_at: datetime


class PaginatedUsers(BaseModel):
    items: list[AdminUserEntry]
    total: int
    page: int
    page_size: int
    total_pages: int


class UpdateUserRolesRequest(BaseModel):
    """Full-state role assignment; panel_role None clears panel access."""

    operation_role: OperationRole
    panel_role: PanelRole | None = None


class SessionLockResponse(BaseModel):
    uuid: UUID
    is_blocked: bool


class NotificationLink(BaseModel):
    """A link the notifications service may render as a button."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=128)
    url: HttpUrl = Field(max_length=2048)


class SubmitNotificationRequest(BaseModel):
    """Body of ``POST /v1/notifications``.

    Mirrors the contract's ``NotificationRequest`` except for ``audience``,
    which the core derives from the authenticated caller and the users
    store instead of trusting the client.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    kind: str = Field(
        min_length=1,
        max_length=128,
        description="Event category, dotted lowercase (e.g. support.user_question).",
    )
    severity: Literal["info", "warning", "error", "critical"]
    subject: str = Field(min_length=1, max_length=256)
    body: str = Field(min_length=1, max_length=16384)
    links: list[NotificationLink] = Field(default_factory=list, max_length=32)
    context: dict[str, Any] = Field(default_factory=dict)


class NotificationAcceptedResponse(BaseModel):
    """The notifications service's delivery id for an accepted request."""

    delivery_id: UUID


class MappingResolveRequest(BaseModel):
    """Body of ``POST /v1/mapping/resolve``.

    Mirrors the mapping contract's ``ResolveRequest``.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    identifier: str = Field(
        min_length=1,
        max_length=1024,
        description="Business identifier to resolve.",
    )
    terraform_provider: TerraformProvider | None = Field(
        default=None,
        description=(
            "Provider the caller already knows the deployment targets, "
            "if any. Echoed back in the response."
        ),
    )


class MappingResolveResponse(BaseModel):
    """What the mapper knows about an identifier.

    Only ``repo_url`` is guaranteed. ``terraform_provider`` and
    ``scope_id`` are best effort, and ``null`` means "unknown, ask the
    user" rather than "there is none" — the wizard skips the step for
    whichever of them comes back non-null.
    """

    repo_url: str = Field(
        min_length=1,
        max_length=2048,
        description="URL to clone.",
    )
    identifier: str = Field(
        min_length=1,
        max_length=1024,
        description="The request's identifier, echoed verbatim.",
    )
    terraform_provider: TerraformProvider | None = Field(
        default=None,
        description="Provider the deployment targets, or null if unknown.",
    )
    scope_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=1024,
        description=(
            "Cloud scope the deployment targets — Azure subscription id, "
            "GCP project id, AWS account id, OCI compartment OCID — or "
            "null if unknown."
        ),
    )


class ManifestProbeRequest(BaseModel):
    """Request shape of ``POST /v1/manifest/probe``."""

    repo_uri: RepoUri = Field(
        description=(
            "HTTPS repository URI. May carry a userinfo username but must not "
            "embed a password or token."
        ),
    )
    root_module_path: str | None = Field(
        default=None,
        max_length=1024,
        description="Repository-relative path to the Terraform root module; defaults to the repo root.",
    )
    terraform_provider: TerraformProvider = Field(
        description="Cloud the session will run against: decides which variables the platform injects.",
    )

    @field_validator("root_module_path", mode="before")
    @classmethod
    def _relative_path(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if v.startswith("/") or ".." in v.split("/"):
            raise ValueError(
                "root_module_path must be a repo-relative path (not absolute) and must not contain '..' segments"
            )
        return v


class ManifestVariable(BaseModel):
    """An input variable the user has to give a value for."""

    name: str
    type: str | None = Field(
        description="HCL type as declared, e.g. `map(string)`; null when untyped."
    )
    description: str
    required: bool = Field(description="Declared without a default.")
    sensitive: bool = Field(
        description="Declared sensitive: the value is always stored as a secret."
    )


class ManifestVarFile(BaseModel):
    """An optional variables file the user may pick, passed as `-var-file`."""

    path: str = Field(description="Relative to the root module.")
    selected: bool = Field(description="Currently picked in the manifest.")
    sets: list[str] = Field(
        description="Variables the file sets: picking it answers those among `missing_variables`.",
    )


class ManifestProviderChange(BaseModel):
    """A provider whose requirement changed since the manifest was written."""

    name: str
    before: str | None = Field(
        description="`source constraints` before; null when added."
    )
    after: str | None = Field(
        description="`source constraints` now; null when removed."
    )


class ManifestProbeResponse(BaseModel):
    """Where a root module's manifest stands, and what the user must answer."""

    status: Literal["not_found", "up_to_date", "drifted"] = Field(
        description=(
            "`not_found`: never configured. `up_to_date`: nothing changed. "
            "`drifted`: the configuration changed since the manifest was written."
        ),
    )
    needs_input: bool = Field(
        description=(
            "Whether the first session call must carry `manifest` answers. When false, "
            "the session sets the manifest up (or brings it up to date) on its own."
        ),
    )
    missing_variables: list[ManifestVariable] = Field(
        description="Variables to answer: required ones nothing covers, and secrets whose value is gone.",
    )
    selectable_var_files: list[ManifestVarFile] = Field(
        description="Optional var files to choose from (answer with `manifest.var_files`).",
    )
    missing_var_files: list[str] = Field(
        description="Picked var files that no longer exist: a new selection is needed.",
    )
    provider_changes: list[ManifestProviderChange]

    @classmethod
    def from_resolution(cls, resolution: ManifestResolution) -> "ManifestProbeResponse":
        selected = set(resolution.manifest.var_files) if resolution.manifest else set()
        return cls(
            status=resolution.status.value,
            needs_input=resolution.needs_input,
            missing_variables=[
                ManifestVariable(
                    name=v.name,
                    type=v.type,
                    description=v.description,
                    required=v.required,
                    sensitive=v.sensitive,
                )
                for v in resolution.missing_variables
            ],
            selectable_var_files=[
                ManifestVarFile(
                    path=f.path, selected=f.path in selected, sets=sorted(f.assigns)
                )
                for f in resolution.selectable_var_files
            ],
            missing_var_files=list(resolution.missing_var_files),
            provider_changes=[
                ManifestProviderChange(
                    name=c.name,
                    before=_provider_text(c.before),
                    after=_provider_text(c.after),
                )
                for c in resolution.provider_changes
            ],
        )


def _provider_text(provider: ProviderRequirement | None) -> str | None:
    if provider is None:
        return None
    return " ".join([provider.source, *provider.version_constraints])
