# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

FROM python:3.13-slim AS base

ARG NEBULA_UID=10001
ARG NEBULA_GID=10001
RUN groupadd --gid "${NEBULA_GID}" nebula \
    && useradd --uid "${NEBULA_UID}" --gid "${NEBULA_GID}" \
        --create-home --home-dir /home/nebula --shell /usr/sbin/nologin nebula \
    && mkdir -p /data && chown nebula:nebula /data

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=120 \
    UV_CONCURRENT_DOWNLOADS=4 \
    PATH="/app/.venv/bin:$PATH"

COPY services/authz/pyproject.toml services/authz/uv.lock ./

RUN uv sync --frozen --no-default-groups

COPY --chown=nebula:nebula services/authz/src ./src

USER ${NEBULA_UID}:${NEBULA_GID}

EXPOSE 8083

CMD ["fastapi", "run", "src/main.py", "--port", "8083"]
