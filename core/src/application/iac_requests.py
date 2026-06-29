# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Request models for the URI-driven, session-iterating IaC endpoints.

Every request is exactly one of:
  - first call: {repo_uri, cloud, environment, user_id, q, ...}
  - iteration:  {session_id, user_id, q, ...}
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class _BaseIacRequest(BaseModel):
    repo_uri: Annotated[
        str | None,
        Field(
            description="Repository URI (first call only). Mutually exclusive with session_id."
        ),
    ] = None
    session_id: Annotated[
        str | None,
        Field(
            description="Existing session id (iteration call). Mutually exclusive with repo_uri.",
            pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        ),
    ] = None
    cloud: Annotated[
        Literal["azure", "gcp", "aws", "oci", "kubernetes"] | None,
        Field(description="Cloud (first call only)."),
    ] = None
    environment: Annotated[
        Literal["dev", "pre", "pro"] | None,
        Field(description="Environment (first call only)."),
    ] = None
    user_id: Annotated[
        str, Field(description="Caller identity. Required on every call.")
    ]
    q: Annotated[str, Field(min_length=1, description="User query for this call.")]
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
    def _validate_iac_path(cls, v):
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
        if has_uri and (self.cloud is None or self.environment is None):
            raise ValueError(
                "First call (repo_uri) requires `cloud` and `environment`."
            )
        if has_sid and self.iac_path is not None:
            raise ValueError(
                "iac_path is set only on the first call; iteration calls inherit it from the session."
            )
        return self


class GenerateRequest(_BaseIacRequest):
    pass


class DriftRequest(_BaseIacRequest):
    is_partial: bool = False


class ApplyRequest(_BaseIacRequest):
    terraform_targets: list[str] = Field(default_factory=list)
