# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv

FROM python:3.13-slim@sha256:bb2988715db2cf7ace7b53f38f3cffbef7c7046a656bee66245eb0ed386e2e81 AS base

ARG NEBULA_UID=10001
ARG NEBULA_GID=10001
RUN groupadd --gid "${NEBULA_GID}" nebula \
    && useradd --uid "${NEBULA_UID}" --gid "${NEBULA_GID}" \
        --create-home --home-dir /home/nebula --shell /usr/sbin/nologin nebula

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=120 \
    UV_CONCURRENT_DOWNLOADS=4 \
    PATH="/app/.venv/bin:$PATH"

COPY services/notifications/pyproject.toml services/notifications/uv.lock ./

RUN uv sync --locked --no-default-groups

COPY --chown=nebula:nebula services/notifications/src ./src

USER ${NEBULA_UID}:${NEBULA_GID}

EXPOSE 8080

CMD ["fastapi", "run", "src/main.py", "--port", "8080"]
