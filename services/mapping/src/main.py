"""FastAPI application for the mapping reference implementation.

Identity passthrough: the input ``identifier`` is returned unchanged as
both the ``repo_url`` and the canonical ``project`` name. This is enough
for OSS users who clone real repo URLs directly; production deployments
substitute their own implementation against the same contract.
"""

from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .auth import verify_bearer_token
from .config import Config
from .models import Health, Problem, ResolveRequest, ResolveResponse


config = Config.from_env()


app = FastAPI(
    title="Nebula Mapping Service",
    version="1.0.0",
    description="Reference implementation of contracts/openapi/mapping.v1.yaml.",
)


# Mapping is the one Nebula service the browser calls directly, so CORS
# is part of the contract surface here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


def _problem(status_code: int, title: str, detail: str | None = None) -> JSONResponse:
    payload = Problem(
        type="about:blank", title=title, status=status_code, detail=detail
    ).model_dump(exclude_none=True)
    return JSONResponse(
        status_code=status_code,
        content=payload,
        media_type="application/problem+json",
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return _problem(exc.status_code, exc.detail or "HTTP error")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return _problem(422, "Request validation failed", str(exc))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return _problem(500, "Internal server error", str(exc))


@app.get("/healthz", response_model=Health, tags=["ops"])
async def healthz() -> Health:
    return Health(status="ok")


@app.post(
    "/v1/resolve",
    response_model=ResolveResponse,
    status_code=status.HTTP_200_OK,
    tags=["resolve"],
)
async def resolve(
    body: ResolveRequest,
    authorization: str | None = Header(default=None),
) -> ResolveResponse:
    verify_bearer_token(config, authorization)

    # Identity passthrough: the identifier IS the repo URL. The canonical
    # project echoes the identifier, truncated to fit the contract's
    # `project` length cap (which is shorter than `identifier`'s because
    # project values are used as cloud/resource-group names downstream).
    return ResolveResponse(
        repo_url=body.identifier,
        project=body.identifier[:128],
    )
