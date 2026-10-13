# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

FROM ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 AS uv

FROM python:3.13-slim@sha256:bb2988715db2cf7ace7b53f38f3cffbef7c7046a656bee66245eb0ed386e2e81 AS base

ARG KUMOSS_UID=10001
ARG KUMOSS_GID=10001
RUN groupadd --gid "${KUMOSS_GID}" kumoss \
    && useradd --uid "${KUMOSS_UID}" --gid "${KUMOSS_GID}" \
        --create-home --home-dir /home/kumoss --shell /usr/sbin/nologin kumoss \
    && mkdir -p /data && chown kumoss:kumoss /data

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=120 \
    UV_CONCURRENT_DOWNLOADS=4 \
    PATH="/app/.venv/bin:$PATH"

COPY services/authz/pyproject.toml services/authz/uv.lock ./

RUN uv sync --locked --no-default-groups

COPY --chown=kumoss:kumoss services/authz/src ./src

USER ${KUMOSS_UID}:${KUMOSS_GID}

EXPOSE 8083

CMD ["fastapi", "run", "src/main.py", "--port", "8083"]
