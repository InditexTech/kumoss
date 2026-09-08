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

# Both IaC engines ship in the image; IAC_BINARY selects at runtime:
# `tofu` (the default) or `terraform` — no rebuild needed to switch.
ARG TERRAFORM_VERSION=1.11.1
COPY --from=tofu /usr/local/bin/tofu /usr/local/bin/tofu
# Cloud CLIs for `POST /v1/import/scope-resource-ids` (az / gcloud / aws).
ARG AWSCLI_VERSION=2.28.0
ARG GCLOUD_VERSION=540.0.0
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl unzip ca-certificates \
    && curl -fsSL "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" -o /tmp/terraform.zip \
    && unzip /tmp/terraform.zip -d /usr/local/bin \
    && rm /tmp/terraform.zip \
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
