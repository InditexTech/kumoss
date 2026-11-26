FROM ghcr.io/astral-sh/uv:0.13.10@sha256:a3ea1357342c1a4bf9a0c53a3deb1b55379aefa037338d8113d5771efa01774f AS uv

# terraform-config-inspect has no binary releases: build it from a pinned
# commit. Static (CGO off) so it runs on the bookworm base below.
FROM golang:1.27-bookworm@sha256:4fa7c968ba93f1635670522dbb01a2c78150443e1385746924566079f36570ea AS config-inspect
ARG TERRAFORM_CONFIG_INSPECT_VERSION=v0.0.0-20260904064934-75d64de68c31
# Same extra CA roots as the runtime stage: the Go module proxy is fetched
# over HTTPS too.
COPY --from=host-certs / /usr/local/share/ca-certificates/
RUN update-ca-certificates
RUN CGO_ENABLED=0 GOBIN=/out go install \
    "github.com/hashicorp/terraform-config-inspect@${TERRAFORM_CONFIG_INSPECT_VERSION}"

# Policy engine for the compliance check: the static build (no libc
# dependency) from OPA's official image, pinned by digest.
FROM openpolicyagent/opa:1.22.4-static@sha256:12cecac5a174368f7d3f09d3a19d040ebe0c91d576e520335ae7a985a26e39d3 AS opa

FROM python:3.15-bookworm@sha256:6f060cab421d9509c6c6a6a7762c651baf03c3f1d0145befe16b688762b7fe81

# Minimal apt deps the core actually uses at runtime: git for cloning user
# repos, ripgrep for the workspace inspection tools, curl for general use.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Extra CA roots from the "host-certs" build context (docker/certs, empty
# by default; the override points it at the host's corporate roots behind a
# TLS-inspecting proxy). Build-time HTTPS — the Python index — needs them
# to anchor the proxy's re-signed chain.
COPY --from=host-certs / /usr/local/share/ca-certificates/
RUN update-ca-certificates

# Unprivileged runtime identity. The uid/gid MUST match the iac image's
# (same ARG names and defaults in services/iac/Dockerfile): both
# containers share the `workspaces` volume read-write, and the IaC
# engine must be able to write lock, plan and state files into the
# clones the core creates.
ARG KUMOSS_UID=10001
ARG KUMOSS_GID=10001
RUN groupadd --gid "${KUMOSS_GID}" kumoss \
    && useradd --uid "${KUMOSS_UID}" --gid "${KUMOSS_GID}" \
        --create-home --home-dir /home/kumoss --shell /usr/sbin/nologin kumoss \
    && mkdir -p /workspaces && chown kumoss:kumoss /workspaces

# config.yaml
COPY config.yaml /etc/kumoss/

COPY --from=uv /uv /uvx /bin/
COPY --from=config-inspect /out/terraform-config-inspect /usr/local/bin/
COPY --from=opa /opa /usr/local/bin/opa

WORKDIR /usr/src/app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_CONCURRENT_DOWNLOADS=4 \
    PATH="/usr/src/app/.venv/bin:$PATH" \
    HOME=/home/kumoss

COPY core/pyproject.toml core/uv.lock ./

RUN uv sync --locked --no-install-project --no-default-groups

COPY --chown=kumoss:kumoss core/src ./src
COPY --chown=kumoss:kumoss core/prompts ./prompts
COPY core/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

USER ${KUMOSS_UID}:${KUMOSS_GID}

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["fastapi", "run", "src/main.py"]
