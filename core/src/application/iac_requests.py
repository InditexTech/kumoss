# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Request models for the URI-driven, session-iterating IaC endpoints."""

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from src.shared.constants import TerraformProvider


class UserRequest(BaseModel):
    user_id: Annotated[
        str, Field(description="Caller identity. Required on every call.")
    ]


class SessionRequest(UserRequest):
    """Base for operations that require an existing session."""

    session_id: Annotated[
        UUID,
        Field(
            description="Existing session id. Required for this operation.",
            examples=["917d0485-a0a2-4c34-8f33-a89d28aba9b0"],
        ),
    ]


class BaseIacRequest(UserRequest):
    session_id: Annotated[
        UUID | None,
        Field(
            description="Existing session id (iteration call). Mutually exclusive with any other parameter but user_id and q.",
            examples=["917d0485-a0a2-4c34-8f33-a89d28aba9b0"],
        ),
    ] = None
    repo_uri: Annotated[
        str | None,
        Field(
            description="Repository URI (first call only). Mutually exclusive with session_id.",
            examples=["Https://github.com/org/iac-repo.git"],
        ),
    ] = None
    scope_id: Annotated[
        str | None,
        Field(
            description="""Infrastructure scope id:
                        - Azure -> subscription id
                        - GCP -> project id
                        - AWS -> account id"""
        ),
    ] = None
    terraform_providers: Annotated[
        TerraformProvider | None,
        Field(
            description="Terraform providers where the operation will take place (first call only)."
        ),
    ] = None
    iac_path: Annotated[
        str | None,
        Field(
            description=(
                "Repository-relative path to the IaC root (e.g. 'environments/dev'). "
                "Defaults to repo root. First call only; omit on iteration calls."
            ),
        ),
    ] = None

    @field_validator("iac_path", mode="before")
    @classmethod
    def _validate_iac_path(cls, v: str):
        if v is None or v == "":
            return None
        if v.startswith("/") or ".." in v.split("/"):
            raise ValueError(
                "iac_path must be a repo-relative path (not absolute) and must not contain '..' segments"
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
        if has_sid and self.iac_path is not None:
            raise ValueError(
                "iac_path is set only on the first call; iteration calls inherit it from the session."
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


class ImportRequest(BaseIacRequest):
    q: Annotated[
        str,
        Field(
            min_length=1,
            description="User query for this call.",
            examples=["Import the storage account staweu1001"],
        ),
    ]

    @model_validator(mode="after")
    def _scope_id_exist_if_repo_uri(self):
        if self.repo_uri is not None and (
            self.scope_id is None or self.scope_id.strip() == ""
        ):
            raise ValueError("The `scope_id` must be provided when `repo_uri` is set.")
        return self


class ApplyRequest(SessionRequest):
    pass
