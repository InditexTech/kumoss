# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Stub PDP for conformance testing.

Always-allow or always-deny based on the ``STUB_DECISION`` env var
(default: ``true``). When ``STUB_TOKEN`` is set, requests without a
matching ``Authorization: Bearer <STUB_TOKEN>`` header receive 401.

    STUB_DECISION=true uvicorn stub:app --port 8083
"""

from __future__ import annotations

import os
from enum import Enum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="Stub AuthZEN PDP")

DECISION = os.environ.get("STUB_DECISION", "true").lower() == "true"
STUB_TOKEN = os.environ.get("STUB_TOKEN", "")


@app.exception_handler(RequestValidationError)
async def _validation_error(_request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "type": "about:blank",
            "title": "Unprocessable Entity",
            "status": 422,
            "detail": str(exc),
        },
        media_type="application/problem+json",
    )


@app.middleware("http")
async def _check_bearer(request: Request, call_next):
    if STUB_TOKEN and request.url.path != "/healthz":
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {STUB_TOKEN}":
            return JSONResponse(
                status_code=401,
                content={"type": "about:blank", "title": "Unauthorized", "status": 401},
                headers={"WWW-Authenticate": "Bearer"},
                media_type="application/problem+json",
            )
    return await call_next(request)


class ActionName(str, Enum):
    generate = "generate"
    drift = "drift"
    import_ = "import"
    apply = "apply"
    pr_create = "pr.create"
    pr_merge = "pr.merge"


class SubjectType(str, Enum):
    user = "user"


class ResourceType(str, Enum):
    scope = "scope"


class Provider(str, Enum):
    azure = "azure"
    gcp = "gcp"
    aws = "aws"
    oci = "oci"
    kubernetes = "kubernetes"
    vmware = "vmware"


class SubjectProperties(BaseModel):
    model_config = {"extra": "allow"}
    issuer: str | None = None
    email: str | None = None


class Subject(BaseModel):
    model_config = {"extra": "forbid"}
    type: SubjectType
    id: str
    properties: SubjectProperties | None = None


class Action(BaseModel):
    model_config = {"extra": "forbid"}
    name: ActionName
    properties: dict[str, object] = {}


class ResourceProperties(BaseModel):
    model_config = {"extra": "allow"}
    provider: Provider | None = None
    repo_uri: str | None = None
    root_module_path: str | None = None


class Resource(BaseModel):
    model_config = {"extra": "forbid"}
    type: ResourceType
    id: str
    properties: ResourceProperties | None = None


class AccessEvaluationRequest(BaseModel):
    model_config = {"extra": "forbid"}
    subject: Subject
    action: Action
    resource: Resource


@app.post("/access/v1/evaluation")
async def evaluate(body: AccessEvaluationRequest) -> dict:
    return {"decision": DECISION}


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
