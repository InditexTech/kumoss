# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# IaC engine: OpenTofu, taken from the official minimal image (the
# install method the OpenTofu project documents for custom images).
FROM ghcr.io/opentofu/opentofu:1.13.2-minimal@sha256:622dc6bb98b105c18f53cf419ab64a4f3b88bd9f8c16cc978cf89e4202f4613f AS tofu

FROM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv

FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS base

# Unprivileged runtime identity. The uid/gid MUST match the core image's
# (same ARG names and defaults in core/Dockerfile): both containers
# share the `workspaces` volume read-write.
ARG KUMOSS_UID=10001
ARG KUMOSS_GID=10001
RUN groupadd --gid "${KUMOSS_GID}" kumoss \
    && useradd --uid "${KUMOSS_UID}" --gid "${KUMOSS_GID}" \
        --create-home --home-dir /home/kumoss --shell /usr/sbin/nologin kumoss \
    && mkdir -p /workspaces && chown kumoss:kumoss /workspaces

WORKDIR /app

COPY --from=uv /uv /uvx /bin/

# Terraform CLI installation. TARGETARCH is set by BuildKit (amd64, arm64),
# which matches HashiCorp's release naming.
ARG TERRAFORM_VERSION=1.16.0
ARG TARGETARCH
COPY --from=tofu /usr/local/bin/tofu /usr/local/bin/tofu
RUN tf_zip="terraform_${TERRAFORM_VERSION}_linux_${TARGETARCH}.zip" \
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
    HOME=/home/kumoss

COPY services/iac/pyproject.toml services/iac/uv.lock ./

RUN uv sync --locked --no-default-groups

COPY --chown=kumoss:kumoss services/iac/src ./src

USER ${KUMOSS_UID}:${KUMOSS_GID}

EXPOSE 8082

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8082", "--timeout-keep-alive", "75"]
