# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# IaC engine: OpenTofu, taken from the official minimal image (the
# install method the OpenTofu project documents for custom images).
FROM ghcr.io/opentofu/opentofu:1.12.7-minimal@sha256:1349f86c125d1e72d63b9ef7f9492b5a4368820a7bc7c1e1f0f8374e02543973 AS tofu

FROM python:3.13-slim AS base

# Unprivileged runtime identity. The uid/gid MUST match the core image's
# (same ARG names and defaults in core/Dockerfile): both containers
# share the `workspaces` volume read-write.
ARG NEBULA_UID=10001
ARG NEBULA_GID=10001
RUN groupadd --gid "${NEBULA_GID}" nebula \
    && useradd --uid "${NEBULA_UID}" --gid "${NEBULA_GID}" \
        --create-home --home-dir /home/nebula --shell /usr/sbin/nologin nebula \
    && mkdir -p /workspaces && chown nebula:nebula /workspaces

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Terraform CLI installation
ARG TERRAFORM_VERSION=1.16.0
COPY --from=tofu /usr/local/bin/tofu /usr/local/bin/tofu
RUN tf_zip="terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl unzip ca-certificates \
    && curl -fsSL "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/${tf_zip}" -o "/tmp/${tf_zip}" \
    && curl -fsSL "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_SHA256SUMS" -o /tmp/terraform_SHA256SUMS \
    && (cd /tmp && grep " ${tf_zip}\$" terraform_SHA256SUMS | sha256sum -c -) \
    && unzip -q "/tmp/${tf_zip}" -d /usr/local/bin \
    && rm "/tmp/${tf_zip}" /tmp/terraform_SHA256SUMS \
    && apt-get purge -y unzip \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=120 \
    UV_CONCURRENT_DOWNLOADS=4 \
    PATH="/app/.venv/bin:$PATH" \
    HOME=/home/nebula

COPY services/iac/pyproject.toml services/iac/uv.lock ./

RUN uv sync --frozen --no-default-groups

COPY --chown=nebula:nebula services/iac/src ./src

USER ${NEBULA_UID}:${NEBULA_GID}

EXPOSE 8082

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8082", "--timeout-keep-alive", "75"]
