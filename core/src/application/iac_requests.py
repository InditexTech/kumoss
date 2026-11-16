# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Request models for the URI-driven, session-iterating IaC endpoints."""

from typing import Annotated
from urllib.parse import urlparse
from uuid import UUID

from pydantic import (
    AfterValidator,
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from src.domains.value_objects.manifest import VariableAnswer
from src.shared.constants import TerraformProvider
from src.shared.utils.urls import is_https_url


def _validate_repo_uri(repo_uri: str) -> str:
    """Accept only https repository URIs that carry no secret in their userinfo.

    Any other transport (SSH, `git://`, `http://`, `file://`, a local path)
    is rejected: pull requests are opened and merged over the provider's
    HTTPS REST API, and the core's git client is set up for HTTPS only.

    A userinfo *username* is not a secret and is passed through untouched:
    Azure DevOps' portal clone URL carries an `<org>@` prefix. Only a
    password component rejects the URI, and it counts as present even when
    empty (`user:@host`) — that shape is a credential the user failed to
    paste, not a bare URI.
    """
    repo_uri = repo_uri.strip()
    if not is_https_url(repo_uri):
        raise ValueError(
            "repo_uri must be an https:// URL (e.g. `https://github.com/org/repo.git`); "
            "SSH, git://, http://, file:// and local paths are not supported."
        )
    parsed = urlparse(repo_uri)
    if parsed.password is not None:
        raise ValueError(
            "repo_uri must not embed a password or token; pass the repository URI "
            "without the `:<secret>` part (a bare `user@host` prefix is fine)."
        )
    return repo_uri


RepoUri = Annotated[str, AfterValidator(_validate_repo_uri)]


class ManifestVariableAnswer(BaseModel):
    """The user's value for one input variable of the root module."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[
        str,
        Field(
            pattern=r"^[A-Za-z_][A-Za-z0-9_-]{0,127}$",
            description="Variable name, as listed by `POST /v1/manifest/probe`.",
        ),
    ]
    value: Annotated[
        JsonValue,
        Field(
            description="Value of any JSON type matching the variable's declared type.",
            repr=False,
        ),
    ]
    sensitive: Annotated[
        bool | None,
        Field(
            description=(
                "Store the value as a secret instead of in the committed manifest. "
                "Omit to keep the variable's current classification; a variable the "
                "code declares sensitive is always stored as a secret."
            ),
        ),
    ] = None


class ManifestAnswers(BaseModel):
    """Answers for the inputs ``POST /v1/manifest/probe`` reported as needed."""

    model_config = ConfigDict(extra="forbid")

    variables: Annotated[
        list[ManifestVariableAnswer],
        Field(max_length=1024, description="Values for the variables asked for."),
    ] = []
    var_files: Annotated[
        list[str] | None,
        Field(
            max_length=64,
            description=(
                "Optional var files to use, in order, from the probe's `selectable_var_files`. "
                "Omit to keep the current selection; an empty list selects none."
            ),
        ),
    ] = None

    @model_validator(mode="after")
    def _unique_names(self):
        names = [v.name for v in self.variables]
        if len(set(names)) != len(names):
            raise ValueError("Each variable may be answered only once.")
        return self

    def answers(self) -> dict[str, VariableAnswer]:
        return {
            v.name: VariableAnswer(value=v.value, sensitive=v.sensitive)
            for v in self.variables
        }


class SessionRequest(BaseModel):
    """Base for operations that require an existing session."""

    session_id: Annotated[
        UUID,
        Field(
            description="Existing session id. Required for this operation.",
            examples=["917d0485-a0a2-4c34-8f33-a89d28aba9b0"],
        ),
    ]


class BaseIacRequest(BaseModel):
    session_id: Annotated[
        UUID | None,
        Field(
            description="Existing session id (iteration call). Mutually exclusive with any other parameter but q.",
            examples=["917d0485-a0a2-4c34-8f33-a89d28aba9b0"],
        ),
    ] = None
    repo_uri: Annotated[
        RepoUri | None,
        Field(
            description=(
                "HTTPS repository URI (first call only). Mutually exclusive with session_id. "
                "May carry a userinfo username (e.g. `https://org@dev.azure.com/...`) "
                "but must not embed a password or token."
            ),
            examples=["Https://github.com/org/iac-repo.git"],
        ),
    ] = None
    scope_id: Annotated[
        str | None,
        Field(
            min_length=1,
            description="""Infrastructure scope id (first call only). Required with repo_uri:
                        - Azure -> subscription id
                        - GCP -> project id
                        - AWS -> account id
                        - OCI -> compartment OCID
                        - Kubernetes -> no cloud scope; any stable identifier
                        - VMware -> vSphere datacenter name""",
        ),
    ] = None
    terraform_providers: Annotated[
        TerraformProvider | None,
        Field(
            description="Terraform providers where the operation will take place (first call only)."
        ),
    ] = None
    root_module_path: Annotated[
        str | None,
        Field(
            # `iac_path` is the deprecated pre-rename spelling, still accepted on input.
            validation_alias=AliasChoices("root_module_path", "iac_path"),
            description=(
                "Repository-relative path to the Terraform root module (e.g. 'environments/dev'). "
                "Defaults to repo root. First call only; omit on iteration calls. "
                "`iac_path` is accepted as a deprecated alias."
            ),
        ),
    ] = None

    manifest: Annotated[
        ManifestAnswers | None,
        Field(
            description=(
                "Answers for the root module's inputs (first call only). Needed when "
                "`POST /v1/manifest/probe` reports `needs_input`; the session saves them "
                "to the root module's manifest before running."
            ),
        ),
    ] = None

    @field_validator("root_module_path", mode="before")
    @classmethod
    def _validate_root_module_path(cls, v: str):
        if v is None or v == "":
            return None
        if v.startswith("/") or ".." in v.split("/"):
            raise ValueError(
                "root_module_path must be a repo-relative path (not absolute) and must not contain '..' segments"
            )
        return v

    @model_validator(mode="after")
    def _exactly_one_of_uri_or_session(self):
        has_uri = self.repo_uri is not None
        has_sid = self.session_id is not None
        if has_uri == has_sid:
            raise ValueError(
                "Exactly one of `repo_uri` or `session_id` must be provided."
            )
        if has_uri and (self.terraform_providers is None):
            raise ValueError("First call (repo_uri) requires `terraform_providers`.")
        if has_uri and (self.scope_id is None):
            raise ValueError("First call (repo_uri) requires `scope_id`.")
        if has_sid and self.root_module_path is not None:
            raise ValueError(
                "root_module_path is set only on the first call; iteration calls inherit it from the session."
            )
        if has_sid and self.manifest is not None:
            raise ValueError(
                "manifest is set only on the first call; iteration calls reuse the session's."
            )
        return self


class GenerateRequest(BaseIacRequest):
    q: Annotated[
        str,
        Field(
            min_length=1,
            description="User query for this call.",
            examples=[
                "Create a storage account and store the secrets in the key vault 001"
            ],
        ),
    ]


class DriftRequest(BaseIacRequest):
    is_partial: bool = False
    q: Annotated[
        str,
        Field(
            min_length=1,
            description="User query for this call.",
            examples=["Resolve the drift in the storage account staweu1001"],
        ),
    ]

    @model_validator(mode="after")
    def _partial_requires_query(self):
        if self.is_partial and (not self.q or not self.q.strip()):
            raise ValueError("Partial drift detection requires a non-empty `q`.")
        return self


class ImportRequest(BaseIacRequest):
    is_partial: bool = False
    q: Annotated[
        str,
        Field(
            min_length=1,
            description="User query for this call.",
            examples=[
                "Import every unmanaged resource in the subscription",
                "Import the storage account staweu1001",
            ],
        ),
    ]

    @model_validator(mode="after")
    def _scope_id_exist_if_repo_uri(self):
        if self.repo_uri is not None and (
            self.scope_id is None or self.scope_id.strip() == ""
        ):
            raise ValueError("The `scope_id` must be provided when `repo_uri` is set.")
        return self

    @model_validator(mode="after")
    def _partial_requires_query(self):
        if self.is_partial and (not self.q or not self.q.strip()):
            raise ValueError("Partial import requires a non-empty `q`.")
        return self


class ApplyRequest(SessionRequest):
    pass
