# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# IaC engine: OpenTofu, taken from the official minimal image (the
# install method the OpenTofu project documents for custom images).
# Digest-pinned so the build is reproducible and integrity-checked;
# bump tag + digest together when upgrading.
FROM ghcr.io/opentofu/opentofu:1.12.6-minimal@sha256:2fedbb3e956b083582543dabb76eba17e9f961dfd055311ea054a6191cfae9dd AS tofu

FROM python:3.13-slim AS base

WORKDIR /app

# IaC engines. OpenTofu (MPL-2.0) is always installed and is the
# default (IAC_BINARY=opentofu). Genuine HashiCorp Terraform (BUSL-1.1) is
# opt-in: build with --build-arg INSTALL_TERRAFORM=1 to install a real
# `terraform` binary alongside `tofu`, then select it at runtime with
# IAC_BINARY=terraform. The default image ships OpenTofu only, so no
# BUSL-licensed binary is distributed unless you ask for it.
#
# When Terraform is NOT installed, a `terraform` -> `tofu` symlink keeps
# deployments that still set TERRAFORM_BINARY=terraform (deprecated; see
# env.sample) working against the bundled OpenTofu engine.
ARG INSTALL_TERRAFORM=0
ARG TERRAFORM_VERSION=1.16.0
COPY --from=tofu /usr/local/bin/tofu /usr/local/bin/tofu
RUN if [ "$INSTALL_TERRAFORM" = "1" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends curl unzip ca-certificates \
        && curl -fsSL "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" -o /tmp/terraform.zip \
        && unzip -q /tmp/terraform.zip -d /usr/local/bin \
        && rm /tmp/terraform.zip \
        && apt-get purge -y unzip \
        && rm -rf /var/lib/apt/lists/*; \
    else \
        ln -s /usr/local/bin/tofu /usr/local/bin/terraform; \
    fi

# Cloud CLIs for `POST /v1/import/scope-resource-ids` (az / gcloud / aws).
ARG AWSCLI_VERSION=2.28.0
ARG GCLOUD_VERSION=540.0.0
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl unzip ca-certificates \
    && curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64-${AWSCLI_VERSION}.zip" -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/awscliv2.zip /tmp/aws \
    && curl -fsSL "https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-${GCLOUD_VERSION}-linux-x86_64.tar.gz" \
    | tar -xz -C /usr/local \
    && ln -s /usr/local/google-cloud-sdk/bin/gcloud /usr/local/bin/gcloud \
    && apt-get purge -y unzip \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

# az is pip-installed (simplest route on a python base image); the
# `az graph` command group lives in the resource-graph extension.
RUN pip install --no-cache-dir azure-cli \
    && az extension add --name resource-graph

COPY pyproject.toml ./
RUN uv pip install --system --no-cache .

COPY src ./src

EXPOSE 8082

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8082", "--timeout-keep-alive", "75"]
